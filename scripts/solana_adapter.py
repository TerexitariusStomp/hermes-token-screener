#!/usr/bin/env python3
"""
Solana Program Adapter: Direct program-level transaction construction.
Uses Jupiter API for route planning, but builds/signs/sends transactions directly via RPC.

Pattern: API (route) → instruction construction → simulate → sign → send
NOT:     API (route) → API (build tx) → sign → send
"""

import os
import base64
import base58
import logging
from typing import Dict, Optional, Tuple

import requests
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.instruction import Instruction, AccountMeta
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
# TOR proxy - route all external HTTP through SOCKS5
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-token-screener"))
import hermes_screener.tor_config

import logging

# PumpSwap direct trading module (bypasses pumpfun-cli)
from pumpswap import (
    build_pumpswap_buy_instructions,
    build_pumpswap_sell_instructions,
    get_pool_by_mint,
    parse_pool_data,
    get_fee_recipients,
    calculate_pumpswap_price,
    get_token_program_id,
)

# ==================== PROGRAM IDS ====================

JUPITER_V6 = Pubkey.from_string("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")
RAYDIUM_CLMM = Pubkey.from_string("CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK")
RAYDIUM_CPMM = Pubkey.from_string("CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C")
ORCA_WHIRLPOOL = Pubkey.from_string("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc")
METEORA_DLMM = Pubkey.from_string("LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo")

# Token program
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022_PROGRAM = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ASSOCIATED_TOKEN_PROGRAM = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

# Well-known mints
SOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")
WSOL_MINT = SOL_MINT  # Wrapped SOL = native SOL

# ==================== TOKEN REGISTRY ====================

TOKENS = {
    "SOL": {"mint": "So11111111111111111111111111111111111111112", "decimals": 9},
    "USDC": {"mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "decimals": 6},
    "USDT": {"mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "decimals": 6},
    "BONK": {"mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "decimals": 5},
    "WIF": {"mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "decimals": 6},
    "POPCAT": {"mint": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "decimals": 9},
    "JUP": {"mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "decimals": 6},
    "RAY": {"mint": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", "decimals": 6},
    "ORCA": {"mint": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE", "decimals": 6},
    "PYTH": {"mint": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "decimals": 6},
}


class SolanaProgramAdapter:
    """Direct Solana program interaction via RPC. Uses Jupiter API for routing only."""

    def __init__(self, rpc_url: str = None, private_key: str = None):
        self.rpc_url = rpc_url or os.environ.get(
            "SOLANA_RPC_URL",
            "https://mainnet.helius-rpc.com/?api-key=bb6ff3e9-e38d-4362-9e7a-669a00d497a8",
        )
        self.client = Client(self.rpc_url)
        self.keypair = None

        if private_key:
            self._init_keypair(private_key)
        else:
            pk = os.environ.get("SOLANA_PRIVATE_KEY") or os.environ.get(
                "WALLET_PRIVATE_KEY_SOLANA", ""
            )
            if pk:
                self._init_keypair(pk)

    def _init_keypair(self, private_key: str):
        """Initialize keypair from various formats."""
        try:
            if len(private_key) in [87, 88]:
                # Base58 format
                self.keypair = Keypair.from_base58_string(private_key)
            elif len(private_key) == 64:
                # Hex format
                self.keypair = Keypair.from_bytes(bytes.fromhex(private_key))
            elif len(private_key) == 128:
                # Uint8Array hex
                self.keypair = Keypair.from_bytes(bytes.fromhex(private_key))
            logger.info(f"Solana wallet: {self.keypair.pubkey()}")
        except Exception as e:
            logger.error(f"Keypair init failed: {e}")

    # ==================== ACCOUNT OPERATIONS ====================

    def get_balance(self, wallet: str = None) -> float:
        """Get SOL balance."""
        try:
            pubkey = Pubkey.from_string(wallet) if wallet else self.keypair.pubkey()
            resp = self.client.get_balance(pubkey)
            return resp.value / 1e9
        except Exception as e:
            logger.error(f"Balance error: {e}")
            return 0.0

    def get_token_balance(self, mint: str, wallet: str = None) -> int:
        """Get SPL token balance in base units. Supports both Token and Token-2022."""
        try:
            wallet_pk = Pubkey.from_string(wallet) if wallet else self.keypair.pubkey()
            mint_pk = Pubkey.from_string(mint)

            # Find associated token account (auto-detects Token vs Token-2022)
            ata = self._get_ata(wallet_pk, mint_pk)
            resp = self.client.get_account_info(ata)

            if resp.value:
                data_raw = resp.value.data
                # Handle both tuple (data, encoding) and raw bytes formats
                if isinstance(data_raw, tuple):
                    data = base64.b64decode(data_raw[1])
                elif isinstance(data_raw, str):
                    data = base64.b64decode(data_raw)
                else:
                    data = bytes(data_raw)
                # Amount is at offset 64 (32 mint + 32 owner), 8 bytes little-endian u64
                amount = int.from_bytes(data[64:72], "little")
                return amount
            return 0
        except Exception as e:
            logger.debug(f"Token balance error: {e}")
            return 0

    def _get_ata(self, owner: Pubkey, mint: Pubkey) -> Pubkey:
        """Derive associated token account address.

        Detects whether mint uses Token or Token-2022 program and
        derives ATA accordingly.
        """
        from solders.pubkey import Pubkey as PK

        TOKEN_2022_PROGRAM = Pubkey.from_string(
            "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
        )

        # Check which token program owns the mint
        try:
            mint_info = self.client.get_account_info(mint)
            if mint_info.value:
                owner_program = mint_info.value.owner
                token_program = owner_program
            else:
                token_program = TOKEN_PROGRAM
        except Exception:
            token_program = TOKEN_PROGRAM

        # ATA = find_program_address([owner, token_program, mint], ASSOCIATED_TOKEN_PROGRAM)
        seeds = [bytes(owner), bytes(token_program), bytes(mint)]
        ata, _ = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM)
        return ata

    def close_wsol_ata(self) -> Optional[str]:
        """Close WSOL ATA, returning lamports to wallet as native SOL."""
        if not self.keypair:
            logger.error("No keypair for WSOL unwrap")
            return None
        try:
            wallet = self.keypair.pubkey()
            wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")

            ata = self._get_ata(wallet, wsol_mint)

            # Check if ATA exists and has balance
            resp = self.client.get_token_account_balance(ata)
            if not resp or not resp.value or int(resp.value.amount) <= 0:
                logger.debug("No WSOL to unwrap")
                return None

            # CloseAccount instruction = 9
            data = bytes([9])
            keys = [
                AccountMeta(pubkey=ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=wallet, is_signer=False, is_writable=True),
                AccountMeta(pubkey=wallet, is_signer=True, is_writable=False),
            ]
            ix = Instruction(program_id=TOKEN_PROGRAM, accounts=keys, data=data)

            blockhash = self.client.get_latest_blockhash().value.blockhash
            msg = MessageV0.try_compile(
                payer=wallet,
                instructions=[ix],
                address_lookup_table_accounts=[],
                recent_blockhash=blockhash,
            )
            tx = VersionedTransaction(msg, [self.keypair])
            sig = self.client.send_transaction(tx, opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed"))
            logger.info(f"WSOL unwrap tx: {sig.value}")
            return str(sig.value)
        except Exception as e:
            logger.error(f"WSOL unwrap failed: {e}")
            return None

    # ==================== JUPITER QUOTE ====================

    def jupiter_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Jupiter API v1."""
        try:
            resp = requests.get(
                "https://api.jup.ag/swap/v1/quote",
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(amount),
                    "slippageBps": slippage_bps,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Jupiter quote error: {e}")
        return {}

    def _get_realtime_priority_fee_micro_lamports(self) -> int:
        """Fetch recent Solana prioritization fees from RPC and return a sane micro-lamports/CU value."""
        try:
            resp = requests.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getRecentPrioritizationFees",
                    "params": [],
                },
                timeout=6,
            )
            if resp.status_code == 200:
                rows = resp.json().get("result", []) or []
                fees = sorted(
                    int(r.get("prioritizationFee", 0))
                    for r in rows
                    if isinstance(r, dict) and r.get("prioritizationFee") is not None
                )
                if fees:
                    # Use p75 to avoid stuck txs during bursts, with guard rails
                    idx = min(len(fees) - 1, int(len(fees) * 0.75))
                    return max(1000, min(fees[idx], 2_000_000))
        except Exception as e:
            logger.debug(f"Priority fee fetch failed: {e}")

        # Fallback: conservative but live-safe
        return 100_000

    # ==================== JUPITER ROUTE → DIRECT TX ====================

    def jupiter_build_tx(
        self, quote: Dict, wrap_unwrap: bool = True
    ) -> Optional[VersionedTransaction]:
        """
        Build a VersionedTransaction from Jupiter quote.

        This uses the Jupiter API to get serialized instructions,
        but we construct the full transaction ourselves using solders.
        The API returns the swap instructions as base64-encoded data
        that we embed in a VersionedTransaction we control.
        """
        if not self.keypair:
            logger.error("No keypair configured")
            return None

        try:
            # Get swap instructions from Jupiter API
            priority_fee = self._get_realtime_priority_fee_micro_lamports()
            logger.info(
                f"Using realtime Solana priority fee: {priority_fee} micro-lamports/CU"
            )

            resp = requests.post(
                "https://api.jup.ag/swap/v1/swap-instructions",
                json={
                    "quoteResponse": quote,
                    "userPublicKey": str(self.keypair.pubkey()),
                    "wrapAndUnwrapSol": wrap_unwrap,
                    "computeUnitPriceMicroLamports": priority_fee,
                    "dynamicComputeUnitLimit": True,
                },
                timeout=15,
            )

            if resp.status_code != 200:
                logger.error(
                    f"Jupiter swap-instructions failed: HTTP {resp.status_code} - {resp.text[:200]}"
                )
                return None

            swap_data = resp.json()

            # Check for error
            if "error" in swap_data:
                logger.error(f"Jupiter error: {swap_data['error']}")
                return None

            # The API returns a serialized transaction OR instruction arrays
            if "swapTransaction" in swap_data:
                # Serialized transaction path - decode and re-sign
                tx_b64 = swap_data["swapTransaction"]
                tx_bytes = base64.b64decode(tx_b64)
                tx = VersionedTransaction.from_bytes(tx_bytes)

                # Re-sign with our keypair (API signs with dummy)
                message = tx.message
                signed_tx = VersionedTransaction(message, [self.keypair])
                return signed_tx

            elif "setupInstructions" in swap_data and "swapInstruction" in swap_data:
                # Instruction array path - build transaction ourselves
                instructions = []

                # Add compute budget instructions first (priority fee, CU limit)
                for cb_ix in swap_data.get("computeBudgetInstructions", []):
                    ix = self._parse_jupiter_instruction(cb_ix)
                    if ix:
                        instructions.append(ix)

                # Add setup instructions (create ATA, wrap SOL, etc.)
                for setup_ix in swap_data.get("setupInstructions", []):
                    ix = self._parse_jupiter_instruction(setup_ix)
                    if ix:
                        instructions.append(ix)

                # Add main swap instruction
                swap_ix = self._parse_jupiter_instruction(swap_data["swapInstruction"])
                if swap_ix:
                    instructions.append(swap_ix)

                # Add cleanup instruction (unwrap SOL, close account)
                cleanup = swap_data.get("cleanupInstruction")
                if cleanup:
                    cleanup_ix = self._parse_jupiter_instruction(cleanup)
                    if cleanup_ix:
                        instructions.append(cleanup_ix)

                # Add other instructions if present
                for other_ix in swap_data.get("otherInstructions", []):
                    ix = self._parse_jupiter_instruction(other_ix)
                    if ix:
                        instructions.append(ix)

                if not instructions:
                    logger.error("No instructions parsed from Jupiter response")
                    return None

                # Load address lookup tables (critical for V0 transactions)
                from solders.address_lookup_table_account import (
                    AddressLookupTableAccount,
                )

                alt_accounts = []
                alt_pubkeys = swap_data.get("addressLookupTableAddresses", [])
                if alt_pubkeys:
                    try:
                        alt_pk_list = [Pubkey.from_string(pk) for pk in alt_pubkeys]
                        alts = self.client.get_multiple_accounts(alt_pk_list)
                        if alts and alts.value:
                            for i, alt_info in enumerate(alts.value):
                                if alt_info and alt_info.data:
                                    # Parse the ALT account data
                                    raw = alt_info.data
                                    if isinstance(raw, tuple):
                                        raw = raw[0]  # (data, encoding) tuple
                                    if isinstance(raw, str):
                                        raw = base64.b64decode(raw)
                                    # ALT layout: 56 byte header + 32 bytes per address
                                    # Skip discriminator (8) + deactivation slot (8) +
                                    # last extended slot (8) + started stuff + authority (33) +
                                    # padding to 56, then 32-byte pubkeys
                                    addresses = []
                                    offset = 56
                                    while offset + 32 <= len(raw):
                                        pk_bytes = raw[offset : offset + 32]
                                        addresses.append(Pubkey.from_bytes(pk_bytes))
                                        offset += 32
                                    alt_accounts.append(
                                        AddressLookupTableAccount(
                                            key=alt_pk_list[i],
                                            addresses=addresses,
                                        )
                                    )
                        logger.info(f"Loaded {len(alt_accounts)} address lookup tables")
                    except Exception as e:
                        logger.warning(f"Failed to load ALTs: {e}, proceeding without")

                # Use blockhash from Jupiter's response (matches the quote timing)
                blockhash_data = swap_data.get("blockhashWithMetadata", {})
                if blockhash_data and "blockhash" in blockhash_data:
                    bh = blockhash_data["blockhash"]
                    # Jupiter may return blockhash in various formats
                    if isinstance(bh, list):
                        bh = bh[0] if bh else None
                    if isinstance(bh, str) and len(bh) > 20:
                        recent_blockhash = Pubkey.from_string(bh)
                    else:
                        # Unexpected format, use client
                        blockhash_resp = self.client.get_latest_blockhash()
                        recent_blockhash = blockhash_resp.value.blockhash
                else:
                    blockhash_resp = self.client.get_latest_blockhash()
                    recent_blockhash = blockhash_resp.value.blockhash

                msg = MessageV0.try_compile(
                    payer=self.keypair.pubkey(),
                    instructions=instructions,
                    address_lookup_table_accounts=alt_accounts,
                    recent_blockhash=recent_blockhash,
                )

                tx = VersionedTransaction(msg, [self.keypair])
                return tx

            else:
                logger.error(
                    f"Unexpected Jupiter response format: {list(swap_data.keys())}"
                )
                return None

        except Exception as e:
            logger.error(f"Jupiter build tx error: {e}")
            import traceback

            traceback.print_exc()
            return None

    def _parse_jupiter_instruction(self, ix_data: Dict) -> Optional[Instruction]:
        """Parse a Jupiter instruction dict into a solders Instruction."""
        try:
            program_id = Pubkey.from_string(ix_data["programId"])
            accounts = []
            for acc in ix_data.get("accounts", []):
                accounts.append(
                    AccountMeta(
                        pubkey=Pubkey.from_string(acc["pubkey"]),
                        is_signer=acc.get("isSigner", False),
                        is_writable=acc.get("isWritable", False),
                    )
                )
            data = base64.b64decode(ix_data["data"])
            return Instruction(program_id=program_id, accounts=accounts, data=data)
        except Exception as e:
            logger.error(f"Parse instruction error: {e}")
            return None

    # ==================== SIMULATE ====================

    def simulate_tx(self, tx: VersionedTransaction) -> Tuple[bool, str]:
        """Simulate a transaction. Returns (success, error_msg)."""
        try:
            resp = self.client.simulate_transaction(tx)
            if resp.value.err:
                err_str = str(resp.value.err)
                logs = resp.value.logs if resp.value.logs else []
                # Find error in logs
                for log in logs:
                    if "Error" in log or "failed" in log.lower():
                        err_str = log
                        break
                return False, err_str
            return True, ""
        except Exception as e:
            return False, str(e)

    # ==================== SEND =============================

    def send_tx(
        self, tx: VersionedTransaction, skip_preflight: bool = False
    ) -> Optional[str]:
        """Send a signed transaction. Returns signature or None."""
        try:
            opts = TxOpts(
                skip_preflight=skip_preflight,
                preflight_commitment="confirmed",
                max_retries=3,
            )
            resp = self.client.send_transaction(tx, opts=opts)
            sig = str(resp.value)
            logger.info(f"TX sent: {sig}")
            return sig
        except Exception as e:
            logger.error(f"Send tx error: {e}")
            return None

    def confirm_tx(self, signature: str, timeout: int = 60) -> bool:
        """Wait for transaction confirmation."""
        try:
            from solders.signature import Signature

            sig_obj = Signature.from_string(signature)
            resp = self.client.confirm_transaction(sig_obj, commitment="confirmed")
            return resp.value is True
        except Exception as e:
            logger.error(f"Confirm error: {e}")
            return False

    # ==================== HIGH-LEVEL SWAP ====================

    def swap(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Optional[str]:
        """
        Execute swap: quote → build → simulate → sign → send → confirm.
        Returns signature or None.
        """
        logger.info(f"Swap: {amount} {input_mint[:8]}.. -> {output_mint[:8]}..")

        # 1. Quote
        quote = self.jupiter_quote(input_mint, output_mint, amount, slippage_bps)
        if not quote:
            logger.error("Quote failed")
            return None

        out_amount = quote.get("outAmount", "?")
        price_impact = quote.get("priceImpactPct", "?")
        logger.info(f"Quote: -> {out_amount} (impact: {price_impact}%)")

        # 2. Build transaction
        tx = self.jupiter_build_tx(quote)
        if not tx:
            logger.error("Build transaction failed")
            return None

        # 3. Simulate
        sim_ok, sim_err = self.simulate_tx(tx)
        if not sim_ok:
            logger.warning(f"Simulation failed: {sim_err} — trying skip_preflight")
            # Try sending with skip_preflight (simulation can be overly strict)
            sig = self.send_tx(tx, skip_preflight=True)
            if not sig:
                return None
            confirmed = self.confirm_tx(sig)
            if confirmed:
                logger.info(f"Swap confirmed (skip_preflight): {sig}")
                return sig
            else:
                logger.warning(f"Swap not yet confirmed: {sig}")
                return sig
        logger.info("Simulation passed")

        # 4. Send
        sig = self.send_tx(tx)
        if not sig:
            return None

        # 5. Confirm
        confirmed = self.confirm_tx(sig)
        if confirmed:
            logger.info(f"Swap confirmed: {sig}")
            return sig
        else:
            logger.warning(f"Swap not yet confirmed: {sig}")
            return sig  # Return anyway, might confirm later

    def swap_by_symbol(
        self, from_symbol: str, to_symbol: str, amount_ui: float, slippage_bps: int = 50
    ) -> Optional[str]:
        """Swap using token symbols and UI amount."""
        from_token = TOKENS.get(from_symbol.upper())
        to_token = TOKENS.get(to_symbol.upper())

        if not from_token or not to_token:
            logger.error(f"Unknown token: {from_symbol} or {to_symbol}")
            return None

        amount_base = int(amount_ui * (10 ** from_token["decimals"]))
        return self.swap(
            from_token["mint"], to_token["mint"], amount_base, slippage_bps
        )

    # ==================== RAYDIUM (DIRECT) ====================

    def raydium_cpmm_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Raydium CPMM API."""
        try:
            resp = requests.get(
                "https://transaction-v1.raydium.io/compute/swap-base-in",
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(amount),
                    "slippageBps": str(slippage_bps),
                    "txVersion": "V0",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return data.get("data", {})
        except Exception as e:
            logger.error(f"Raydium quote error: {e}")
        return {}

    def raydium_build_tx(self, quote_data: Dict) -> Optional[VersionedTransaction]:
        """
        Build VersionedTransaction from Raydium swap data.
        Raydium API returns serialized instructions - we decode and rebuild.
        """
        if not self.keypair:
            return None

        try:
            # Raydium returns instructions in the response
            swap_instructions = quote_data.get("data", [])

            if isinstance(swap_instructions, str):
                # Serialized transaction path
                tx_bytes = base64.b64decode(swap_instructions)
                tx = VersionedTransaction.from_bytes(tx_bytes)
                signed_tx = VersionedTransaction(tx.message, [self.keypair])
                return signed_tx

            # Instruction array path
            instructions = []
            for ix_data in swap_instructions:
                if isinstance(ix_data, dict):
                    ix = self._parse_raydium_instruction(ix_data)
                    if ix:
                        instructions.append(ix)

            if not instructions:
                logger.error("No Raydium instructions parsed")
                return None

            blockhash = self.client.get_latest_blockhash().value.blockhash
            msg = MessageV0.try_compile(
                payer=self.keypair.pubkey(),
                instructions=instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=blockhash,
            )
            return VersionedTransaction(msg, [self.keypair])

        except Exception as e:
            logger.error(f"Raydium build error: {e}")
            return None

    def _parse_raydium_instruction(self, ix_data: Dict) -> Optional[Instruction]:
        """Parse Raydium instruction data."""
        try:
            program_id = Pubkey.from_string(ix_data["programId"])
            accounts = [
                AccountMeta(
                    pubkey=Pubkey.from_string(acc["pubkey"]),
                    is_signer=acc.get("isSigner", False),
                    is_writable=acc.get("isWritable", False),
                )
                for acc in ix_data.get("accounts", [])
            ]
            data = base64.b64decode(ix_data["data"])
            return Instruction(program_id=program_id, accounts=accounts, data=data)
        except Exception as e:
            logger.debug(f"Parse Raydium ix error: {e}")
            return None

    # ==================== METEORA DLMM ====================

    METEORA_API = "https://dlmm-api.meteora.ag"

    def meteora_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Meteora DLMM API."""
        try:
            resp = requests.get(
                f"{self.METEORA_API}/pair/{input_mint}/{output_mint}", timeout=10
            )
            if resp.status_code != 200:
                resp = requests.get(
                    f"{self.METEORA_API}/pair/{output_mint}/{input_mint}", timeout=10
                )
            if resp.status_code == 200:
                pairs = resp.json()
                if isinstance(pairs, list) and pairs:
                    best = max(pairs, key=lambda p: float(p.get("liquidity", "0")))
                    return {
                        "pool": best.get("address", ""),
                        "liquidity": best.get("liquidity", "0"),
                        "source": "meteora_dlmm",
                        "inputMint": input_mint,
                        "outputMint": output_mint,
                    }
        except Exception as e:
            logger.error(f"Meteora quote error: {e}")
        return {}

    def meteora_build_tx(
        self, quote_data: Dict, wallet: str, amount: int, slippage_bps: int = 50
    ) -> Optional[str]:
        """Build swap transaction via Meteora DLMM API."""
        try:
            pool = quote_data.get("pool", "")
            if not pool:
                return None
            resp = requests.post(
                f"{self.METEORA_API}/swap",
                json={
                    "pool": pool,
                    "inputMint": quote_data.get("inputMint", ""),
                    "outputMint": quote_data.get("outputMint", ""),
                    "amount": str(amount),
                    "slippage": slippage_bps / 100,
                    "userPublicKey": wallet,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("tx") or data.get("transaction")
        except Exception as e:
            logger.error(f"Meteora build error: {e}")
        return None

    # ==================== ORCA WHIRLPOOL ====================

    ORCA_API = "https://api.orca.so"

    def orca_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Orca Whirlpool API."""
        try:
            resp = requests.get(f"{self.ORCA_API}/v1/whirlpool/list", timeout=10)
            if resp.status_code == 200:
                pools = resp.json()
                matching = []
                for addr, pool in (pools if isinstance(pools, dict) else {}).items():
                    token_a = pool.get("tokenA", {}).get("mint", "")
                    token_b = pool.get("tokenB", {}).get("mint", "")
                    if (token_a == input_mint and token_b == output_mint) or (
                        token_a == output_mint and token_b == input_mint
                    ):
                        matching.append(
                            {
                                "pool": addr,
                                "liquidity": pool.get("liquidity", "0"),
                                "sqrtPrice": pool.get("sqrtPrice", "0"),
                                "tickSpacing": pool.get("tickSpacing", 0),
                            }
                        )
                if matching:
                    best = max(matching, key=lambda p: int(p.get("liquidity", "0")))
                    return {
                        "pool": best["pool"],
                        "liquidity": best["liquidity"],
                        "sqrtPrice": best.get("sqrtPrice", "0"),
                        "source": "orca_whirlpool",
                        "inputMint": input_mint,
                        "outputMint": output_mint,
                    }
        except Exception as e:
            logger.error(f"Orca quote error: {e}")
        return {}

    def orca_build_tx(
        self, quote_data: Dict, wallet: str, amount: int, slippage_bps: int = 50
    ) -> Optional[str]:
        """Build swap transaction via Orca Whirlpool API."""
        try:
            resp = requests.post(
                f"{self.ORCA_API}/v1/whirlpool/swap",
                json={
                    "pool": quote_data.get("pool", ""),
                    "inputMint": quote_data.get("inputMint", ""),
                    "outputMint": quote_data.get("outputMint", ""),
                    "amount": str(amount),
                    "slippage": slippage_bps / 100,
                    "userPublicKey": wallet,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("tx") or data.get("transaction")
        except Exception as e:
            logger.error(f"Orca build error: {e}")
        return None

    # ==================== PUMPSWAP ====================

    PUMPSWAP_API = "https://frontend-api.pump.fun"

    def pumpswap_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from PumpSwap (pump.fun DEX)."""
        try:
            resp = requests.get(f"{self.PUMPSWAP_API}/coins/{output_mint}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "pool": data.get("mint", output_mint),
                    "bondingCurve": data.get("bonding_curve", ""),
                    "virtualSolReserves": data.get("virtual_sol_reserves", 0),
                    "virtualTokenReserves": data.get("virtual_token_reserves", 0),
                    "source": "pumpswap",
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                }
        except Exception as e:
            logger.error(f"PumpSwap quote error: {e}")
        return {}

    def pumpswap_build_tx(
        self, quote_data: Dict, wallet: str, amount: int, slippage_bps: int = 50
    ) -> Optional[str]:
        """Build swap transaction via PumpSwap API."""
        try:
            resp = requests.post(
                f"{self.PUMPSWAP_API}/swap",
                json={
                    "mint": quote_data.get("outputMint", ""),
                    "bondingCurve": quote_data.get("bondingCurve", ""),
                    "solAmount": amount,
                    "slippageBps": slippage_bps,
                    "userPublicKey": wallet,
                    "action": "buy",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("tx") or data.get("transaction")
        except Exception as e:
            logger.error(f"PumpSwap build error: {e}")
        return None

    # ==================== GUACSWAP (DIRECT ON-CHAIN) ====================

    GUACSWAP_PROGRAM_ID = Pubkey.from_string(
        "Gswppe6ERWKpUTXvRPfXdzHhiCyJvLadVvXGfdpBqcE1"
    )

    def guacswap_find_pool(self, mint_a: str, mint_b: str) -> Optional[str]:
        """Find a GuacSwap pool for a token pair by scanning program accounts."""

        def _search(mint_to_find):
            try:
                resp = requests.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getProgramAccounts",
                        "params": [
                            str(self.GUACSWAP_PROGRAM_ID),
                            {
                                "encoding": "base64",
                                "filters": [
                                    {"memcmp": {"offset": 8, "bytes": mint_to_find}},
                                    {"dataSize": 417},
                                ],
                                "limit": 20,
                            },
                        ],
                    },
                    timeout=15,
                )
                return resp.json().get("result", [])
            except Exception:
                return []

        try:
            # Search with mint_a at offset 8
            for acc in _search(mint_a):
                raw = base64.b64decode(acc["account"]["data"][0])
                stored_b = base58.b58encode(raw[40:72]).decode()
                if stored_b == mint_b:
                    return acc["pubkey"]

            # Search with mint_b at offset 8 (pool might store them in opposite order)
            for acc in _search(mint_b):
                raw = base64.b64decode(acc["account"]["data"][0])
                stored_b = base58.b58encode(raw[40:72]).decode()
                if stored_b == mint_a:
                    return acc["pubkey"]

        except Exception as e:
            logger.error(f"GuacSwap pool search error: {e}")
        return None

    def guacswap_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from GuacSwap by reading pool state directly on-chain.

        Uses constant product formula: output = (reserve_out * amount_in * 997)
                                             / (reserve_in * 1000 + amount_in * 997)
        """
        try:
            pool_addr = self.guacswap_find_pool(input_mint, output_mint)
            if not pool_addr:
                return {}

            # Read pool account
            resp = requests.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getAccountInfo",
                    "params": [pool_addr, {"encoding": "base64"}],
                },
                timeout=10,
            )
            result = resp.json()
            if not (result.get("result") and result["result"].get("value")):
                return {}

            raw = base64.b64decode(result["result"]["value"]["data"][0])
            mint_a = base58.b58encode(raw[8:40]).decode()
            mint_b = base58.b58encode(raw[40:72]).decode()
            vault_a = base58.b58encode(raw[72:104]).decode()
            vault_b = base58.b58encode(raw[104:136]).decode()

            # Determine which vault is input and which is output
            if mint_a == input_mint:
                input_vault = vault_a
                output_vault = vault_b
            elif mint_b == input_mint:
                input_vault = vault_b
                output_vault = vault_a
            elif mint_a == output_mint:
                input_vault = vault_b
                output_vault = vault_a
            else:
                input_vault = vault_a
                output_vault = vault_b

            # Read vault balances
            def get_balance(vault_addr):
                r = requests.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTokenAccountBalance",
                        "params": [vault_addr],
                    },
                    timeout=5,
                )
                rr = r.json()
                if rr.get("result") and rr["result"].get("value"):
                    v = rr["result"]["value"]
                    return int(v.get("amount", "0")), v.get("decimals", 0)
                return 0, 0

            reserve_in, dec_in = get_balance(input_vault)
            reserve_out, dec_out = get_balance(output_vault)

            if reserve_in == 0 or reserve_out == 0:
                return {}

            # Constant product formula with 0.3% fee
            # output = (reserve_out * amount_in * 997) / (reserve_in * 1000 + amount_in * 997)
            numerator = reserve_out * amount * 997
            denominator = reserve_in * 1000 + amount * 997
            amount_out = numerator // denominator

            # Apply slippage
            min_amount_out = amount_out * (10000 - slippage_bps) // 10000

            return {
                "pool": pool_addr,
                "inputMint": input_mint,
                "inAmount": str(amount),
                "outputMint": output_mint,
                "outAmount": str(amount_out),
                "minOutAmount": str(min_amount_out),
                "reserveIn": str(reserve_in),
                "reserveOut": str(reserve_out),
                "vaultIn": input_vault,
                "vaultOut": output_vault,
                "source": "guacswap",
                "priceImpactPct": 0.0,  # TODO: calculate
            }
        except Exception as e:
            logger.error(f"GuacSwap quote error: {e}")
        return {}

    def guacswap_build_tx(
        self, quote_data: Dict, wallet: str, amount: int, slippage_bps: int = 50
    ) -> Optional[str]:
        """Build a GuacSwap swap transaction.

        Constructs raw swap instruction and returns serialized transaction.
        """
        if not self.keypair:
            return None

        try:
            pool = quote_data.get("pool", "")
            input_mint = quote_data.get("inputMint", "")
            output_mint = quote_data.get("outputMint", "")
            vault_in = quote_data.get("vaultIn", "")
            vault_out = quote_data.get("vaultOut", "")
            min_out = int(float(quote_data.get("minOutAmount", "0")))

            if not all([pool, input_mint, output_mint, vault_in, vault_out]):
                return None

            user = self.keypair.pubkey()
            pool_pubkey = Pubkey.from_string(pool)
            vault_in_pubkey = Pubkey.from_string(vault_in)
            vault_out_pubkey = Pubkey.from_string(vault_out)
            input_mint_pubkey = Pubkey.from_string(input_mint)
            output_mint_pubkey = Pubkey.from_string(output_mint)

            # Get user token accounts
            user_input_ata = self._get_ata(user, input_mint_pubkey)
            user_output_ata = self._get_ata(user, output_mint_pubkey)

            # GuacSwap swap instruction discriminator: 0x1e (30)
            swap_data = (
                bytes([0x1E])
                + amount.to_bytes(8, "little")
                + min_out.to_bytes(8, "little")
            )

            # Build account metas
            accounts = [
                AccountMeta(pubkey=user, is_signer=True, is_writable=True),
                AccountMeta(pubkey=user_input_ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=user_output_ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool_pubkey, is_signer=False, is_writable=True),
                AccountMeta(pubkey=vault_in_pubkey, is_signer=False, is_writable=True),
                AccountMeta(pubkey=vault_out_pubkey, is_signer=False, is_writable=True),
                AccountMeta(
                    pubkey=input_mint_pubkey, is_signer=False, is_writable=False
                ),
                AccountMeta(
                    pubkey=output_mint_pubkey, is_signer=False, is_writable=False
                ),
                AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
                AccountMeta(
                    pubkey=Pubkey.from_string("11111111111111111111111111111111"),
                    is_signer=False,
                    is_writable=False,
                ),
            ]

            swap_ix = Instruction(
                program_id=self.GUACSWAP_PROGRAM_ID,
                data=swap_data,
                accounts=accounts,
            )

            instructions = []

            # For SOL input: wrap SOL to WSOL
            if input_mint == str(SOL_MINT):
                # Transfer SOL -> WSOL ATA
                from solders.system_program import (
                    TransferParams,
                    transfer as sys_transfer,
                )

                # Create WSOL ATA if needed
                create_ix = self._get_ata_create_ix(
                    user, user_input_ata, user, SOL_MINT
                )
                if create_ix:
                    instructions.append(create_ix)

                # Transfer SOL to WSOL ATA
                transfer_ix = sys_transfer(
                    TransferParams(
                        from_pubkey=user, to_pubkey=user_input_ata, lamports=amount
                    )
                )
                instructions.append(transfer_ix)

                # Sync native (required for WSOL)
                sync_ix = Instruction(
                    program_id=TOKEN_PROGRAM,
                    data=bytes([17]),  # SyncNative discriminator
                    accounts=[
                        AccountMeta(
                            pubkey=user_input_ata, is_signer=False, is_writable=True
                        )
                    ],
                )
                instructions.append(sync_ix)

            # Create output ATA if needed
            create_out_ix = self._get_ata_create_ix(
                user, user_output_ata, user, output_mint_pubkey
            )
            if create_out_ix:
                instructions.append(create_out_ix)

            instructions.append(swap_ix)

            # Build transaction
            blockhash = self.client.get_latest_blockhash().value.blockhash
            msg = MessageV0.try_compile(
                payer=user,
                instructions=instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=blockhash,
            )
            tx = VersionedTransaction(msg, [self.keypair])
            serialized = base64.b64encode(bytes(tx)).decode()
            return serialized

        except Exception as e:
            logger.error(f"GuacSwap build error: {e}")
            return None

    def _get_ata_create_ix(self, payer, ata, owner, mint):
        """Create instruction to create an Associated Token Account."""
        try:
            # Check if ATA already exists
            bal = self.client.get_token_account_balance(ata)
            if bal.value:
                return None  # Already exists
        except Exception:
            pass

        # Create ATA instruction
        from solders.instruction import Instruction as IX

        # ATA creation data: empty (just the discriminator)
        create_data = bytes([1])  # Create instruction discriminator

        create_ix = IX(
            program_id=Pubkey.from_string(
                "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
            ),
            data=create_data,
            accounts=[
                AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
                AccountMeta(pubkey=ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=owner, is_signer=False, is_writable=False),
                AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
                AccountMeta(
                    pubkey=Pubkey.from_string("11111111111111111111111111111111"),
                    is_signer=False,
                    is_writable=False,
                ),
                AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
                AccountMeta(
                    pubkey=Pubkey.from_string(
                        "SysvarRent111111111111111111111111111111111"
                    ),
                    is_signer=False,
                    is_writable=False,
                ),
            ],
        )
        return create_ix

    # ==================== GENERIC AMM (DIRECT ON-CHAIN) ====================

    def amm_discover_pools(
        self, program_id: str, mint_a: str, mint_b: str, data_size: int = 0
    ) -> list:
        """Discover AMM pools for a token pair from any program."""
        pools = []
        try:
            for search_mint in [mint_a, mint_b]:
                filters = [{"memcmp": {"offset": 8, "bytes": search_mint}}]
                if data_size > 0:
                    filters.append({"dataSize": data_size})

                resp = requests.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getProgramAccounts",
                        "params": [
                            program_id,
                            {"encoding": "base64", "filters": filters, "limit": 20},
                        ],
                    },
                    timeout=15,
                )
                result = resp.json()
                if result.get("result"):
                    for acc in result["result"]:
                        raw = base64.b64decode(acc["account"]["data"][0])
                        stored_a = base58.b58encode(raw[8:40]).decode()
                        stored_b = base58.b58encode(raw[40:72]).decode()
                        pair = {stored_a, stored_b}
                        if mint_a in pair and mint_b in pair:
                            vault_a = base58.b58encode(raw[72:104]).decode()
                            vault_b = base58.b58encode(raw[104:136]).decode()
                            pools.append(
                                {
                                    "pool": acc["pubkey"],
                                    "mint_a": stored_a,
                                    "mint_b": stored_b,
                                    "vault_a": vault_a,
                                    "vault_b": vault_b,
                                    "program": program_id,
                                }
                            )
        except Exception as e:
            logger.error(f"Pool discovery error: {e}")
        return pools

    def amm_quote_constant_product(
        self, pool_data: Dict, input_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Generic constant-product AMM quote from pool state."""
        try:
            vault_a = pool_data.get("vault_a", "")
            vault_b = pool_data.get("vault_b", "")
            mint_a = pool_data.get("mint_a", "")
            mint_b = pool_data.get("mint_b", "")

            bal_a, dec_a = self._get_token_balance(vault_a)
            bal_b, dec_b = self._get_token_balance(vault_b)

            if input_mint == mint_a:
                reserve_in, reserve_out = bal_a, bal_b
                output_mint = mint_b
            else:
                reserve_in, reserve_out = bal_b, bal_a
                output_mint = mint_a

            if reserve_in == 0 or reserve_out == 0:
                return {}

            numerator = reserve_out * amount * 997
            denominator = reserve_in * 1000 + amount * 997
            amount_out = numerator // denominator
            min_out = amount_out * (10000 - slippage_bps) // 10000

            return {
                "pool": pool_data.get("pool", ""),
                "inputMint": input_mint,
                "inAmount": str(amount),
                "outputMint": output_mint,
                "outAmount": str(amount_out),
                "minOutAmount": str(min_out),
                "vaultIn": vault_a if input_mint == mint_a else vault_b,
                "vaultOut": vault_b if input_mint == mint_a else vault_a,
                "reserveIn": str(reserve_in),
                "reserveOut": str(reserve_out),
                "source": "amm_direct",
            }
        except Exception as e:
            logger.error(f"AMM quote error: {e}")
        return {}

    def _get_token_balance(self, vault_addr: str) -> tuple:
        """Get token account balance, returns (amount, decimals)."""
        try:
            resp = requests.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountBalance",
                    "params": [vault_addr],
                },
                timeout=5,
            )
            result = resp.json()
            if result.get("result") and result["result"].get("value"):
                v = result["result"]["value"]
                return int(v.get("amount", "0")), v.get("decimals", 0)
        except Exception:
            pass
        return 0, 0

    # ==================== INVARIANT (DIRECT ON-CHAIN) ====================

    INVARIANT_PROGRAM = Pubkey.from_string(
        "HyaB3W9q6XdA5xwpU4XnSZV94htfmbmqJXZcEbRaJutt"
    )

    def invariant_find_pool(self, mint_a: str, mint_b: str) -> Optional[Dict]:
        """Find Invariant pool for a token pair."""
        try:
            for search_mint in [mint_a, mint_b]:
                resp = requests.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getProgramAccounts",
                        "params": [
                            str(self.INVARIANT_PROGRAM),
                            {
                                "encoding": "base64",
                                "filters": [
                                    {"memcmp": {"offset": 8, "bytes": search_mint}}
                                ],
                                "limit": 20,
                            },
                        ],
                    },
                    timeout=15,
                )
                result = resp.json()
                if result.get("result"):
                    for acc in result["result"]:
                        raw = base64.b64decode(acc["account"]["data"][0])
                        stored_a = base58.b58encode(raw[8:40]).decode()
                        stored_b = base58.b58encode(raw[40:72]).decode()
                        if {stored_a, stored_b} == {mint_a, mint_b}:
                            vault_a = base58.b58encode(raw[72:104]).decode()
                            vault_b = base58.b58encode(raw[104:136]).decode()
                            return {
                                "pool": acc["pubkey"],
                                "mint_a": stored_a,
                                "mint_b": stored_b,
                                "vault_a": vault_a,
                                "vault_b": vault_b,
                            }
        except Exception as e:
            logger.error(f"Invariant pool search error: {e}")
        return None

    def invariant_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Invariant directly on-chain."""
        try:
            pool_data = self.invariant_find_pool(input_mint, output_mint)
            if pool_data:
                pool_data["source"] = "invariant"
                return self.amm_quote_constant_product(
                    pool_data, input_mint, amount, slippage_bps
                )
        except Exception as e:
            logger.error(f"Invariant quote error: {e}")
        return {}

    # ==================== RAYDIUM AMM (DIRECT ON-CHAIN) ====================

    RAYDIUM_AMM_PROGRAM = Pubkey.from_string(
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
    )

    def raydium_amm_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Raydium AMM directly on-chain.

        Raydium AMM pools are 752 bytes. Token mints at offset 400 (token A) and 432 (token B).
        Vaults at offset 8 (coin vault) and 16 (pc vault).
        """
        try:
            for search_mint in [input_mint, output_mint]:
                resp = requests.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getProgramAccounts",
                        "params": [
                            str(self.RAYDIUM_AMM_PROGRAM),
                            {
                                "encoding": "base64",
                                "filters": [
                                    {"memcmp": {"offset": 400, "bytes": search_mint}},
                                    {"dataSize": 752},
                                ],
                                "limit": 10,
                            },
                        ],
                    },
                    timeout=15,
                )
                result = resp.json()
                if result.get("result"):
                    for acc in result["result"]:
                        raw = base64.b64decode(acc["account"]["data"][0])
                        mint_a = base58.b58encode(raw[400:432]).decode()
                        mint_b = base58.b58encode(raw[432:464]).decode()
                        if {mint_a, mint_b} == {input_mint, output_mint}:
                            vault_a = base58.b58encode(raw[8:40]).decode()
                            vault_b = base58.b58encode(raw[16:48]).decode()
                            pool_data = {
                                "pool": acc["pubkey"],
                                "mint_a": mint_a,
                                "mint_b": mint_b,
                                "vault_a": vault_a,
                                "vault_b": vault_b,
                                "source": "raydium_amm",
                            }
                            return self.amm_quote_constant_product(
                                pool_data, input_mint, amount, slippage_bps
                            )
        except Exception as e:
            logger.error(f"Raydium AMM quote error: {e}")
        return {}

    # ==================== GENERIC DEX QUOTE ====================

    def direct_dex_quote(
        self,
        dex: str,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> Dict:
        """Get a direct quote from a specific DEX.

        Routes to the appropriate quote function based on DEX name.
        """
        quote_funcs = {
            "raydium": self.raydium_cpmm_quote,
            "raydium_cpmm": self.raydium_cpmm_quote,
            "raydium_amm": self.raydium_amm_quote,
            "orca": self.orca_quote,
            "meteora": self.meteora_quote,
            "pumpswap": self.pumpswap_quote,
            "guacswap": self.guacswap_quote,
            "invariant": self.invariant_quote,
        }
        func = quote_funcs.get(dex)
        if func:
            try:
                return func(input_mint, output_mint, amount, slippage_bps)
            except Exception as e:
                logger.error(f"Direct quote {dex} error: {e}")
        return {}

    # ==================== SMART ROUTING ====================

    def smart_route(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
        swap_type: str = "buy_small",
    ) -> Optional[Dict]:
        """Smart routing across all Solana DEXs.

        Tries each DEX in priority order using direct on-chain/API quotes.
        Jupiter is the final fallback aggregator.

        swap_type: buy_large, buy_small, buy_memecoin, sell_large, sell_small, stable_swap
        """
        priority = DEX_ROUTING_PRIORITY.get(swap_type, ["raydium_cpmm", "jupiter"])

        for dex in priority:
            try:
                if dex == "jupiter":
                    quote = self.jupiter_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("outAmount"):
                        return {"dex": "jupiter", "quote": quote, "route": swap_type}
                elif dex == "raydium":
                    quote = self.raydium_cpmm_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("outputAmount"):
                        return {"dex": "raydium", "quote": quote, "route": swap_type}
                elif dex == "raydium_cpmm":
                    quote = self.raydium_cpmm_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("outputAmount"):
                        return {
                            "dex": "raydium_cpmm",
                            "quote": quote,
                            "route": swap_type,
                        }
                elif dex == "raydium_amm":
                    quote = self.raydium_amm_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("outAmount"):
                        return {
                            "dex": "raydium_amm",
                            "quote": quote,
                            "route": swap_type,
                        }
                elif dex == "orca":
                    quote = self.orca_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("pool"):
                        return {"dex": "orca", "quote": quote, "route": swap_type}
                elif dex == "meteora":
                    quote = self.meteora_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("pool"):
                        return {"dex": "meteora", "quote": quote, "route": swap_type}
                elif dex == "pumpswap":
                    quote = self.pumpswap_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("pool"):
                        return {"dex": "pumpswap", "quote": quote, "route": swap_type}
                elif dex == "guacswap":
                    quote = self.guacswap_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("pool"):
                        return {"dex": "guacswap", "quote": quote, "route": swap_type}
                elif dex == "invariant":
                    quote = self.invariant_quote(
                        input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("outAmount"):
                        return {"dex": "invariant", "quote": quote, "route": swap_type}
                else:
                    # Generic fallback using direct_dex_quote
                    quote = self.direct_dex_quote(
                        dex, input_mint, output_mint, amount, slippage_bps
                    )
                    if quote and quote.get("outAmount"):
                        return {"dex": dex, "quote": quote, "route": swap_type}
            except Exception as e:
                logger.debug(f"Smart route {dex} failed: {e}")
                continue

        return None

    # ==================== PUMPSWAP ====================

    def pumpswap_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get PumpSwap quote and return expected output amount and pool info."""
        try:
            client = self.client
            base_mint_str = output_mint if input_mint == str(WSOL_MINT) else input_mint
            base_mint = Pubkey.from_string(base_mint_str)
            pool_address, pool_data = get_pool_by_mint(client, base_mint)
            pool = parse_pool_data(pool_data)
            token_program_id = get_token_program_id(client, base_mint)
            base_bal = client.get_token_account_balance(pool["pool_base_token_account"])
            quote_bal = client.get_token_account_balance(pool["pool_quote_token_account"])
            base_reserves = int(base_bal.value.amount) if base_bal.value else 0
            quote_reserves = int(quote_bal.value.amount) if quote_bal.value else 0
            is_buy = input_mint == str(WSOL_MINT)
            if is_buy:
                amount_out, _ = calculate_pumpswap_price(base_reserves, quote_reserves, amount, is_buy=True)
            else:
                amount_out, _ = calculate_pumpswap_price(base_reserves, quote_reserves, amount, is_buy=False)
            min_out = int(amount_out * (1 - slippage_bps / 10000))
            return {
                "pool_address": str(pool_address),
                "pool": pool,
                "token_program_id": str(token_program_id),
                "is_buy": is_buy,
                "amount_out": amount_out,
                "min_out": min_out,
                "base_reserves": base_reserves,
                "quote_reserves": quote_reserves,
                "base_mint": str(base_mint),
            }
        except Exception as e:
            logger.error(f"PumpSwap quote error: {e}")
            return {}

    def pumpswap_buy(self, mint: str, amount_sol: float, slippage_bps: int = 100) -> Optional[str]:
        """Buy tokens on PumpSwap using SOL (wrap->swap). Returns tx signature or None."""
        if not self.keypair:
            logger.error("PumpSwap buy: no keypair")
            return None
        try:
            amount_lamports = int(amount_sol * 1e9)
            mint_pk = Pubkey.from_string(mint)
            pool_address, pool_data = get_pool_by_mint(self.client, mint_pk)
            pool = parse_pool_data(pool_data)
            token_program_id = get_token_program_id(self.client, mint_pk)
            fee_recipient, fee_recipient_ata = get_fee_recipients(self.client)
            quote = self.pumpswap_quote(str(WSOL_MINT), mint, amount_lamports, slippage_bps)
            if not quote:
                logger.error("PumpSwap buy: quote failed")
                return None
            min_tokens_out = quote["min_out"]
            sol_wrap_lamports = amount_lamports
            build_ixs = build_pumpswap_buy_instructions(
                user=self.keypair.pubkey(),
                pool_address=pool_address,
                pool=pool,
                token_program_id=token_program_id,
                fee_recipient=fee_recipient,
                fee_recipient_ata=fee_recipient_ata,
                amount_out=min_tokens_out,
                max_sol_in=amount_lamports * 2,
                sol_wrap_lamports=sol_wrap_lamports,
            )
            recent_blockhash = self.client.get_latest_blockhash().value.blockhash
            msg = MessageV0.try_compile(
                payer=self.keypair.pubkey(),
                instructions=build_ixs,
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash,
            )
            tx = VersionedTransaction(msg, [self.keypair])
            opts = TxOpts(skip_preflight=False, preflight_commitment="confirmed")
            resp = self.client.send_transaction(tx, opts=opts)
            sig = str(resp.value)
            if self.confirm_tx(sig):
                logger.info(f"PumpSwap buy confirmed: {sig}")
                return sig
            logger.warning(f"PumpSwap buy not confirmed: {sig}")
            return sig
        except Exception as e:
            logger.error(f"PumpSwap buy error: {e}")
            return None

    def pumpswap_sell(self, mint: str, token_amount: int, slippage_bps: int = 100) -> Optional[str]:
        """Sell tokens on PumpSwap for WSOL. Returns tx signature or None."""
        if not self.keypair:
            logger.error("PumpSwap sell: no keypair")
            return None
        try:
            mint_pk = Pubkey.from_string(mint)
            pool_address, pool_data = get_pool_by_mint(self.client, mint_pk)
            pool = parse_pool_data(pool_data)
            token_program_id = get_token_program_id(self.client, mint_pk)
            fee_recipient, fee_recipient_ata = get_fee_recipients(self.client)
            quote = self.pumpswap_quote(mint, str(WSOL_MINT), token_amount, slippage_bps)
            if not quote:
                logger.error("PumpSwap sell: quote failed")
                return None
            min_sol_out = quote["min_out"]
            build_ixs = build_pumpswap_sell_instructions(
                user=self.keypair.pubkey(),
                pool_address=pool_address,
                pool=pool,
                token_program_id=token_program_id,
                fee_recipient=fee_recipient,
                fee_recipient_ata=fee_recipient_ata,
                token_amount=token_amount,
                min_sol_out=min_sol_out,
            )
            recent_blockhash = self.client.get_latest_blockhash().value.blockhash
            msg = MessageV0.try_compile(
                payer=self.keypair.pubkey(),
                instructions=build_ixs,
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash,
            )
            tx = VersionedTransaction(msg, [self.keypair])
            opts = TxOpts(skip_preflight=False, preflight_commitment="confirmed")
            resp = self.client.send_transaction(tx, opts=opts)
            sig = str(resp.value)
            if self.confirm_tx(sig):
                logger.info(f"PumpSwap sell confirmed: {sig}")
                return sig
            logger.warning(f"PumpSwap sell not confirmed: {sig}")
            return sig
        except Exception as e:
            logger.error(f"PumpSwap sell error: {e}")
            return None

    def get_dex_info(self, dex_key: str) -> Dict:
        """Get info about a Solana DEX from the registry."""
        return SOLANA_DEX_REGISTRY.get(dex_key, {})

    def list_dexs_by_tvl(self, min_tvl: float = 0) -> list:
        """List all Solana DEXs sorted by TVL."""
        dexs = [
            (k, v) for k, v in SOLANA_DEX_REGISTRY.items() if v.get("tvl", 0) >= min_tvl
        ]
        return sorted(dexs, key=lambda x: x[1].get("tvl", 0), reverse=True)

    # ==================== MULTI-DEX COMPARISON ====================

    def compare_quotes(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Compare quotes across Solana DEXes."""
        quotes = {}

        # Jupiter
        jup = self.jupiter_quote(input_mint, output_mint, amount, slippage_bps)
        if jup:
            quotes["jupiter"] = {
                "output": jup.get("outAmount", "0"),
                "impact": jup.get("priceImpactPct", "0"),
                "routes": len(jup.get("routePlan", [])),
                "source": "program (build tx directly)",
            }

        # Raydium
        ray = self.raydium_cpmm_quote(input_mint, output_mint, amount, slippage_bps)
        if ray:
            quotes["raydium"] = {
                "output": ray.get("outputAmount", "0"),
                "impact": ray.get("priceImpact", 0),
                "source": "program (build tx directly)",
            }

        # Meteora DLMM
        met = self.meteora_quote(input_mint, output_mint, amount, slippage_bps)
        if met:
            quotes["meteora"] = {
                "output": met.get("liquidity", "0"),
                "pool": met.get("pool", ""),
                "source": "meteora_dlmm",
            }

        # Orca Whirlpool
        orc = self.orca_quote(input_mint, output_mint, amount, slippage_bps)
        if orc:
            quotes["orca"] = {
                "output": orc.get("liquidity", "0"),
                "pool": orc.get("pool", ""),
                "source": "orca_whirlpool",
            }

        # PumpSwap
        pump = self.pumpswap_quote(input_mint, output_mint, amount, slippage_bps)
        if pump:
            quotes["pumpswap"] = {
                "pool": pump.get("pool", ""),
                "bondingCurve": pump.get("bondingCurve", ""),
                "source": "pumpswap",
            }

        return quotes


# ═══════════════════════════════════════════════════════════════════════════════
# SOLANA DEX REGISTRY — All known Solana DEXs with addresses and types
# ═══════════════════════════════════════════════════════════════════════════════

SOLANA_DEX_REGISTRY = {
    "raydium": {
        "name": "Raydium AMM",
        "address": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
        "type": "amm",
        "tvl": 998709916,
        "api": "https://transaction-v1.raydium.io",
        "has_api": True,
    },
    "meteora": {
        "name": "Meteora DLMM",
        "address": "METvsvVRapdj9cFLzq4Tr43xK4tAjQfwX76z3n6mWQL",
        "type": "dlmm",
        "tvl": 305128844,
        "api": "https://dlmm-api.meteora.ag",
        "has_api": True,
    },
    "orca": {
        "name": "Orca DEX",
        "address": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
        "type": "whirlpool",
        "tvl": 264857438,
        "api": "https://api.orca.so",
        "has_api": True,
    },
    "pumpswap": {
        "name": "PumpSwap",
        "address": "pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn",
        "type": "bonding_curve",
        "tvl": 210251963,
        "api": "https://frontend-api.pump.fun",
        "has_api": True,
    },
    "sanctum": {
        "name": "Sanctum Infinity",
        "address": "CLoUDKc4Ane7HeQcPpE3YHnznRxhMimJ4MyaUqyHFzAu",
        "type": "lst_router",
        "tvl": 179733132,
        "has_api": False,
    },
    "meteora_damm_v2": {
        "name": "Meteora DAMM V2",
        "address": "METvsvVRapdj9cFLzq4Tr43xK4tAjQfwX76z3n6mWQL",
        "type": "amm",
        "tvl": 36572381,
        "has_api": False,
    },
    "meteora_damm_v1": {
        "name": "Meteora DAMM V1",
        "address": "METvsvVRapdj9cFLzq4Tr43xK4tAjQfwX76z3n6mWQL",
        "type": "amm",
        "tvl": 22390766,
        "has_api": False,
    },
    "manifest": {
        "name": "Manifest Trade",
        "address": "",
        "type": "orderbook",
        "tvl": 18097288,
        "has_api": False,
    },
    "doaar": {
        "name": "DOOAR",
        "address": "",
        "type": "amm",
        "tvl": 5110361,
        "has_api": False,
    },
    "phoenix": {
        "name": "Phoenix Spot",
        "address": "",
        "type": "orderbook",
        "tvl": 2180607,
        "has_api": False,
    },
    "openbook": {
        "name": "OpenBook",
        "address": "",
        "type": "orderbook",
        "tvl": 1046042,
        "has_api": False,
    },
    "invariant": {
        "name": "Invariant",
        "address": "HyaB3W9q6XdA5xwpU4XnSZV94htfmbmqJXZcEbRaJutt",
        "type": "amm",
        "tvl": 312117,
        "has_api": False,
    },
    "skate": {
        "name": "Skate AMM",
        "address": "",
        "type": "amm",
        "tvl": 249767,
        "has_api": False,
    },
    "guacswap": {
        "name": "GuacSwap",
        "address": "Gswppe6ERWKpUTXvRPfXdzHhiCyJvLadVvXGfdpBqcE1",
        "type": "amm",
        "tvl": 65698,
        "has_api": False,
    },
    "aldrin_v1": {
        "name": "Aldrin V1",
        "address": "AMM55ShdkoGRB5jVYPjWziwk8m5MpwyDgsMWHaMSQWH6",
        "type": "amm",
        "tvl": 500000,
        "has_api": False,
    },
    "aldrin_v2": {
        "name": "Aldrin V2",
        "address": "CURVGoZn8zycx6FXwwevgBTB2gVvdbGTEpvMJDbgs2t4",
        "type": "clob",
        "tvl": 500000,
        "has_api": False,
    },
    "orbit_finance": {
        "name": "Orbit Finance",
        "address": "",
        "type": "amm",
        "tvl": 0,
        "has_api": False,
    },
}

# Type-based routing priority: which DEX type to try first for each swap category
DEX_ROUTING_PRIORITY = {
    "buy_large": [
        "raydium_cpmm",
        "raydium_amm",
        "orca",
        "meteora",
        "invariant",
        "guacswap",
        "pumpswap",
        "jupiter",
    ],
    "buy_small": [
        "pumpswap",
        "raydium_cpmm",
        "raydium_amm",
        "guacswap",
        "orca",
        "jupiter",
    ],
    "buy_memecoin": [
        "pumpswap",
        "raydium_amm",
        "raydium_cpmm",
        "guacswap",
        "jupiter",
    ],
    "sell_large": [
        "raydium_cpmm",
        "raydium_amm",
        "orca",
        "meteora",
        "invariant",
        "guacswap",
        "pumpswap",
        "jupiter",
    ],
    "sell_small": [
        "raydium_cpmm",
        "raydium_amm",
        "guacswap",
        "orca",
        "jupiter",
    ],
    "stable_swap": [
        "invariant",
        "raydium_cpmm",
        "orca",
        "jupiter",
    ],
}
