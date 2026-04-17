#!/usr/bin/env python3
"""
Solana Program Adapter: Direct program-level transaction construction.
Uses Jupiter API for route planning, but builds/signs/sends transactions directly via RPC.

Pattern: API (route) → instruction construction → simulate → sign → send
NOT:     API (route) → API (build tx) → sign → send
"""

import os
import json
import time
import base64
import logging
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass

import requests
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.message import MessageV0, to_bytes_versioned
from solders.instruction import Instruction, AccountMeta, CompiledInstruction
from solders.hash import Hash
from solana.rpc.api import Client
from solana.rpc.types import TxOpts

logger = logging.getLogger(__name__)

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
            "SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"
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
        """Get SPL token balance in base units."""
        try:
            wallet_pk = Pubkey.from_string(wallet) if wallet else self.keypair.pubkey()
            mint_pk = Pubkey.from_string(mint)

            # Find associated token account
            ata = self._get_ata(wallet_pk, mint_pk)
            resp = self.client.get_account_info(ata, encoding="base64")

            if resp.value:
                # Parse token account data (layout: mint[32] owner[32] amount[u64] ...)
                data = base64.b64decode(resp.value.data[1])
                # Amount is at offset 64 (32+32), 8 bytes little-endian u64
                amount = int.from_bytes(data[64:72], "little")
                return amount
            return 0
        except Exception as e:
            logger.debug(f"Token balance error: {e}")
            return 0

    def _get_ata(self, owner: Pubkey, mint: Pubkey) -> Pubkey:
        """Derive associated token account address."""
        from solders.pubkey import Pubkey as PK

        # ATA = find_program_address([owner, TOKEN_PROGRAM, mint], ASSOCIATED_TOKEN_PROGRAM)
        seeds = [bytes(owner), bytes(TOKEN_PROGRAM), bytes(mint)]
        ata, _ = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM)
        return ata

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
            resp = requests.post(
                "https://api.jup.ag/swap/v1/swap-instructions",
                json={
                    "quoteResponse": quote,
                    "userPublicKey": str(self.keypair.pubkey()),
                    "wrapAndUnwrapSol": wrap_unwrap,
                    "computeUnitPriceMicroLamports": 50000,  # priority fee
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

                if not instructions:
                    logger.error("No instructions parsed from Jupiter response")
                    return None

                # Build message
                blockhash_resp = self.client.get_latest_blockhash()
                recent_blockhash = blockhash_resp.value.blockhash

                msg = MessageV0.try_compile(
                    payer=self.keypair.pubkey(),
                    instructions=instructions,
                    address_lookup_table_accounts=[],
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
            resp = self.client.confirm_transaction(signature, commitment="confirmed")
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
            logger.error(f"Simulation failed: {sim_err}")
            return None
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
