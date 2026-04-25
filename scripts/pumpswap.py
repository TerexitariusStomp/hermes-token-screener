"""
PumpSwap AMM direct trading — bypasses pumpfun-cli.
Uses pool_address from existing pump_info to avoid pool-fetch RPC issues.
"""

import struct
from typing import Dict, Optional, Tuple
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from spl.token.instructions import (
    get_associated_token_address,
    create_idempotent_associated_token_account,
    TransferParams,
    transfer,
    SyncNativeParams,
    sync_native,
)
from solana.rpc.api import Client
import logging

logger = logging.getLogger(__name__)

# ─── Program IDs ─────────────────────────────────────────────────────────────
PUMP_AMM_PROGRAM = Pubkey.from_string("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA")
PUMP_SWAP_GLOBAL_CONFIG = Pubkey.from_string("ADyA8hdefvWN2dbGGWFotbzWxrAvLW83WG6QCVXvJKqw")
PUMP_SWAP_EVENT_AUTHORITY = Pubkey.from_string("6FQ9Z6b2db4xbiD5c8Ei7vt4kKnT39R9aDbvr2kQ6ZEM")
PUMP_FEE_PROGRAM = Pubkey.from_string("pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZZ")

SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022_PROGRAM = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ASSOCIATED_TOKEN_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
WSOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")

# Instruction discriminators from PumpSwap IDL
PUMPSWAP_BUY_DISCRIMINATOR = bytes([126, 219, 92, 174, 145, 73, 28, 41])
PUMPSWAP_SELL_DISCRIMINATOR = bytes([232, 122, 108, 41, 60, 206, 241, 154])

# Standard fee recipient (fallback when global config unavailable)
STANDARD_PUMPSWAP_FEE_RECIPIENT = Pubkey.from_string("7VtfL8fvgNfhz17qKRMjzQEXgbdpnHHHQRh54R9jP2RJ")


# ─── PDA derivation ──────────────────────────────────────────────────────────
def derive_pool_v2(base_mint: Pubkey) -> Pubkey:
    addr, _ = Pubkey.find_program_address([b"pool-v2", bytes(base_mint)], PUMP_AMM_PROGRAM)
    return addr


def derive_creator_vault(coin_creator: Pubkey) -> Pubkey:
    addr, _ = Pubkey.find_program_address([b"creator-vault", bytes(coin_creator)], PUMP_AMM_PROGRAM)
    return addr


def derive_amm_fee_config() -> Pubkey:
    addr, _ = Pubkey.find_program_address([b"fee-config"], PUMP_AMM_PROGRAM)
    return addr


def derive_global_volume_accumulator() -> Pubkey:
    addr, _ = Pubkey.find_program_address([b"global-volume-accumulator"], PUMP_SWAP_GLOBAL_CONFIG)
    return addr


def derive_user_volume_accumulator(user: Pubkey) -> Pubkey:
    addr, _ = Pubkey.find_program_address([b"user-volume-accumulator", bytes(user)], PUMP_SWAP_GLOBAL_CONFIG)
    return addr


# ─── Pool data ───────────────────────────────────────────────────────────────
def get_pool_by_mint(client: Client, mint: Pubkey) -> Tuple[Pubkey, bytes]:
    pool_address = derive_pool_v2(mint)
    resp = client.get_account_info(pool_address)
    if not resp.value:
        raise RuntimeError(f"No PumpSwap pool for {mint}")
    return pool_address, bytes(resp.value.data)


def parse_pool_data(data: bytes) -> Dict:
    """Parse binary PumpSwap pool account data."""
    pool_bump = data[8]
    index = struct.unpack_from("<H", data, 9)[0]
    creator = Pubkey.from_bytes(data[11:43])
    base_mint = Pubkey.from_bytes(data[43:75])
    quote_mint = Pubkey.from_bytes(data[75:107])
    lp_mint = Pubkey.from_bytes(data[107:139])
    pool_base_token_account = Pubkey.from_bytes(data[139:171])
    pool_quote_token_account = Pubkey.from_bytes(data[171:203])
    lp_supply = struct.unpack_from("<Q", data, 203)[0]
    coin_creator = Pubkey.from_bytes(data[211:243])
    return {
        "pool_bump": pool_bump,
        "index": index,
        "creator": creator,
        "base_mint": base_mint,
        "quote_mint": quote_mint,
        "lp_mint": lp_mint,
        "pool_base_token_account": pool_base_token_account,
        "pool_quote_token_account": pool_quote_token_account,
        "lp_supply": lp_supply,
        "coin_creator": coin_creator,
    }


def get_fee_recipients(client: Client) -> Tuple[Pubkey, Pubkey]:
    resp = client.get_account_info(PUMP_SWAP_GLOBAL_CONFIG)
    if resp.value:
        config_data = bytes(resp.value.data)
        # protocol_fee_recipient offset = 104 (from contracts.py)
        off = 104
        fee_recipient = Pubkey.from_bytes(config_data[off:off+32])
    else:
        fee_recipient = STANDARD_PUMPSWAP_FEE_RECIPIENT
    fee_recipient_ata = get_associated_token_address(fee_recipient, WSOL_MINT, TOKEN_PROGRAM)
    return fee_recipient, fee_recipient_ata


# ─── CPMM math ───────────────────────────────────────────────────────────────
def calculate_pumpswap_price(
    base_reserves: int,
    quote_reserves: int,
    amount_in: int,
    is_buy: bool,
) -> Tuple[int, int]:
    """
    Constant-product formula: x * y = k
    Returns (amount_out, new_reserves_for_quote_side).
    """
    if is_buy:
        new_quote = quote_reserves + amount_in
        base_out = int(base_reserves * amount_in / new_quote)
        return base_out, new_quote
    else:
        new_base = base_reserves + amount_in
        quote_out = int(quote_reserves * amount_in / new_base)
        return quote_out, new_base


# ─── Instruction builders ────────────────────────────────────────────────────
def build_pumpswap_buy_instructions(
    user: Pubkey,
    pool_address: Pubkey,
    pool: Dict,
    token_program_id: Pubkey,
    fee_recipient: Pubkey,
    fee_recipient_ata: Pubkey,
    amount_out: int,
    max_sol_in: int,
    sol_wrap_lamports: int,
) -> list[Instruction]:
    user_wsol_ata = get_associated_token_address(user, WSOL_MINT, TOKEN_PROGRAM)
    user_token_ata = get_associated_token_address(user, pool["base_mint"], token_program_id)

    coin_creator = pool["coin_creator"]
    creator_vault_authority = derive_creator_vault(coin_creator)
    creator_vault_ata = get_associated_token_address(creator_vault_authority, WSOL_MINT, TOKEN_PROGRAM)

    create_wsol_ata = create_idempotent_associated_token_account(
        payer=user, owner=user, mint=WSOL_MINT, token_program_id=TOKEN_PROGRAM
    )

    from solders.system_program import TransferParams, transfer
    transfer_ix = transfer(TransferParams(from_pubkey=user, to_pubkey=user_wsol_ata, lamports=sol_wrap_lamports))

    sync_ix = sync_native(SyncNativeParams(program_id=TOKEN_PROGRAM, account=user_wsol_ata))

    create_token_ata = create_idempotent_associated_token_account(
        payer=user, owner=user, mint=pool["base_mint"], token_program_id=token_program_id
    )

    pool_v2 = derive_pool_v2(pool["base_mint"])

    buy_accounts = [
        AccountMeta(pubkey=pool_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user, is_signer=True, is_writable=True),
        AccountMeta(pubkey=PUMP_SWAP_GLOBAL_CONFIG, is_signer=False, is_writable=False),
        AccountMeta(pubkey=pool["base_mint"], is_signer=False, is_writable=False),
        AccountMeta(pubkey=WSOL_MINT, is_signer=False, is_writable=False),
        AccountMeta(pubkey=user_token_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user_wsol_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=pool["pool_base_token_account"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=pool["pool_quote_token_account"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=fee_recipient, is_signer=False, is_writable=False),
        AccountMeta(pubkey=fee_recipient_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=token_program_id, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYSTEM_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=ASSOCIATED_TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=PUMP_SWAP_EVENT_AUTHORITY, is_signer=False, is_writable=False),
        AccountMeta(pubkey=PUMP_AMM_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=creator_vault_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=creator_vault_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=derive_global_volume_accumulator(), is_signer=False, is_writable=False),
        AccountMeta(pubkey=derive_user_volume_accumulator(user), is_signer=False, is_writable=True),
        AccountMeta(pubkey=derive_amm_fee_config(), is_signer=False, is_writable=False),
        AccountMeta(pubkey=PUMP_FEE_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=pool_v2, is_signer=False, is_writable=False),
    ]

    instruction_data = (
        PUMPSWAP_BUY_DISCRIMINATOR
        + struct.pack("<Q", amount_out)
        + struct.pack("<Q", max_sol_in)
        + b"\\x01"  # track_volume = True
    )

    buy_ix = Instruction(program_id=PUMP_AMM_PROGRAM, accounts=buy_accounts, data=instruction_data)
    return [create_wsol_ata, transfer_ix, sync_ix, create_token_ata, buy_ix]


def build_pumpswap_sell_instructions(
    user: Pubkey,
    pool_address: Pubkey,
    pool: Dict,
    token_program_id: Pubkey,
    fee_recipient: Pubkey,
    fee_recipient_ata: Pubkey,
    token_amount: int,
    min_sol_out: int,
) -> list[Instruction]:
    user_wsol_ata = get_associated_token_address(user, WSOL_MINT, TOKEN_PROGRAM)
    user_token_ata = get_associated_token_address(user, pool["base_mint"], token_program_id)

    coin_creator = pool["coin_creator"]
    creator_vault_authority = derive_creator_vault(coin_creator)
    creator_vault_ata = get_associated_token_address(creator_vault_authority, WSOL_MINT, TOKEN_PROGRAM)

    create_wsol_ata = create_idempotent_associated_token_account(
        payer=user, owner=user, mint=WSOL_MINT, token_program_id=TOKEN_PROGRAM
    )

    pool_v2 = derive_pool_v2(pool["base_mint"])

    sell_accounts = [
        AccountMeta(pubkey=pool_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user, is_signer=True, is_writable=True),
        AccountMeta(pubkey=PUMP_SWAP_GLOBAL_CONFIG, is_signer=False, is_writable=False),
        AccountMeta(pubkey=pool["base_mint"], is_signer=False, is_writable=False),
        AccountMeta(pubkey=WSOL_MINT, is_signer=False, is_writable=False),
        AccountMeta(pubkey=user_token_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user_wsol_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=pool["pool_base_token_account"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=pool["pool_quote_token_account"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=fee_recipient, is_signer=False, is_writable=False),
        AccountMeta(pubkey=fee_recipient_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=token_program_id, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYSTEM_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=ASSOCIATED_TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=PUMP_SWAP_EVENT_AUTHORITY, is_signer=False, is_writable=False),
        AccountMeta(pubkey=PUMP_AMM_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=creator_vault_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=creator_vault_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=derive_amm_fee_config(), is_signer=False, is_writable=False),
        AccountMeta(pubkey=PUMP_FEE_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=pool_v2, is_signer=False, is_writable=False),
    ]

    instruction_data = PUMPSWAP_SELL_DISCRIMINATOR + struct.pack("<Q", token_amount) + struct.pack("<Q", min_sol_out)
    sell_ix = Instruction(program_id=PUMP_AMM_PROGRAM, accounts=sell_accounts, data=instruction_data)
    return [create_wsol_ata, sell_ix]
