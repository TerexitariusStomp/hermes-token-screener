#!/usr/bin/env python3
"""
DEX Aggregator Trading Bot
Uses multiple DEX aggregators for optimal trading across Base and Solana.
"""

import os
import sys
import json
import time
import logging
from decimal import Decimal
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3
# TOR proxy - route all external HTTP through SOCKS5
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-token-screener"))
import hermes_screener.tor_config

load_dotenv(os.path.expanduser("~/.hermes/.env"))

# === SINGLE INSTANCE LOCK ===
LOCKFILE = "/tmp/dex_aggregator_trader.lock"


def acquire_lock():
    """Acquire exclusive lock via PID-based lockfile. Exit if another instance is running."""

    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE, "r") as f:
                old_pid = int(f.read().strip())
            # Check if process is alive
            os.kill(old_pid, 0)  # signal 0 = check existence
            print(
                f"[LOCK] Instance already running (PID {old_pid}), exiting.",
                file=sys.stderr,
            )
            sys.exit(0)
        except (ValueError, ProcessLookupError):
            # Stale lockfile or PID doesn't exist -- take over
            print("[LOCK] Stale lockfile found, taking over.", file=sys.stderr)
        except PermissionError:
            # Process exists but we can't signal it (different user) -- exit safe
            print(
                f"[LOCK] Instance running (PID {old_pid}, permission denied), exiting.",
                file=sys.stderr,
            )
            sys.exit(0)

    # Write our PID
    with open(LOCKFILE, "w") as f:
        f.write(str(os.getpid()))


def release_lock():
    """Remove lockfile if we own it."""
    try:
        with open(LOCKFILE, "r") as f:
            pid = int(f.read().strip())
        if pid == os.getpid():
            os.remove(LOCKFILE)
    except (FileNotFoundError, ValueError):
        pass


import atexit

atexit.register(release_lock)


# Clean up on signals too
def _signal_handler(sig, frame):
    release_lock()
    sys.exit(0)


import signal

signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

acquire_lock()
# === END SINGLE INSTANCE LOCK ===

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Import contract executor (direct on-chain calls)
try:
    from contract_executor import ContractExecutor
    from protocol_registry import PROTOCOL_REGISTRY, TOKEN_REGISTRY, NATIVE_ETH

    HAS_CONTRACT_EXECUTOR = True
except ImportError:
    HAS_CONTRACT_EXECUTOR = False
    NATIVE_ETH = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

# Import Solana program adapter
try:
    from solana_adapter import SolanaProgramAdapter, TOKENS as SOLANA_TOKENS

    HAS_SOLANA_ADAPTER = True
except ImportError:
    HAS_SOLANA_ADAPTER = False


class DexAggregatorTrader:
    """
    Multi-chain trading using DEX aggregators.
    Supports: Jupiter, KyberSwap, OpenOcean, LiFi, Velora, Portals.fi, Enso, Oku
    """

    # API Keys
    LIFI_API_KEY = os.environ.get(
        "LIFI_API_KEY",
        "5507bdb8-0e83-4f80-8c76-238718004832.d1d06e6b-5be9-4725-93b5-75e62b90ccd4",
    )
    JUPITER_API_KEY = os.environ.get(
        "JUPITER_API_KEY",
        "jup_92630f2f0da7d0cc8923a674bd54252f958a103c237de78da89ba6a0494117d9",
    )
    PORTALS_BEARER = "04a791c6-7f56-4bcc-b0fd-a00cc0157cde"

    # API Endpoints
    JUPITER_API = "https://api.jup.ag/swap/v1"  # quote-api.jup.ag is DNS-blocked; use api.jup.ag/swap/v1
    JUPITER_API_V1 = "https://api.jup.ag/swap/v1"
    KYBERSWAP_API = "https://aggregator-api.kyberswap.com"
    OPENOCEAN_API = "https://open-api.openocean.finance/v3"
    LIFI_API = "https://li.quest/v1"
    VELORA_API = "https://api.paraswap.io"
    PORTALS_API = "https://api.portals.fi/v2"
    ENSO_API = "https://api.enso.build/api/v1"
    OKU_API = "https://api.oku.trade"
    ODOS_API = "https://api.odos.xyz"
    COW_API = "https://api.cow.fi/base"
    RAYDIUM_API = "https://transaction-v1.raydium.io"
    METEORA_API = "https://dlmm-api.meteora.ag"
    ORCA_API = "https://api.orca.so"
    PUMPSWAP_API = "https://frontend-api.pump.fun"
    GMX_API = "https://arbitrum-api.gmxinfra.io"

    # Trade history file for persistence across restarts
    TRADE_HISTORY_FILE = os.path.expanduser("~/.hermes/data/trade_history.json")

    # Gas reserves: minimum balance to keep for transactions
    # Base L2: typical tx costs ~0.000001-0.000005 ETH; reserve 0.00003 ETH (6-30 txs)
    BASE_GAS_RESERVE = Decimal("0.00003")
    # Solana: reserve $0.15 USD worth of SOL (calculated dynamically per run)
    _SOLANA_GAS_RESERVE_USD = Decimal("0.15")
    SOLANA_GAS_RESERVE = Decimal("0.001")  # fallback, refreshed in __init__

    def __init__(self):
        self.evm_account = None
        self.solana_keypair = None
        self.w3 = None
        self.contract_executor = None
        self.solana_adapter = None
        self._enso_rate_limited = False
        # Trade history: track failed attempts and completed trades
        self.trade_history = self._load_trade_history()
        # Wallet discovery is expensive (many RPC calls). Keep it optional + cached
        # so one slow RPC cannot stall the whole trading loop for long periods.
        self.wallet_discovery_enabled = (
            os.environ.get("HERMES_ENABLE_WALLET_DISCOVERY", "0").strip() == "1"
        )
        self.wallet_discovery_interval_sec = int(
            os.environ.get("HERMES_WALLET_DISCOVERY_INTERVAL_SEC", "900")
        )
        self._last_wallet_discovery_ts = 0.0
        self._cached_wallet_tokens = {}
        self.initialize()
        # Refresh SOL gas reserve from live price
        self._refresh_sol_gas_reserve()

    def initialize(self):
        """Initialize wallets."""
        try:
            # EVM wallet
            evm_pk = os.environ.get("WALLET_PRIVATE_KEY_BASE", "")
            if evm_pk:
                if evm_pk.startswith("0x"):
                    evm_pk = evm_pk[2:]
                self.evm_account = Account.from_key(bytes.fromhex(evm_pk))
                logger.info(f"EVM Wallet: {self.evm_account.address}")

            # Solana wallet
            solana_pk = os.environ.get("WALLET_PRIVATE_KEY_SOLANA") or os.environ.get(
                "SOLANA_PRIVATE_KEY", ""
            )
            if solana_pk:
                try:
                    from solders.keypair import Keypair

                    if len(solana_pk) == 64:
                        try:
                            self.solana_keypair = Keypair.from_base58_string(solana_pk)
                        except:
                            self.solana_keypair = Keypair.from_seed(
                                bytes.fromhex(solana_pk[:64])
                            )
                    elif len(solana_pk) in [87, 88]:
                        self.solana_keypair = Keypair.from_base58_string(solana_pk)
                    if self.solana_keypair:
                        logger.info(f"Solana Wallet: {self.solana_keypair.pubkey()}")

                    # Set Helius RPC for Solana
                    self.solana_rpc = os.environ.get(
                        "SOLANA_RPC_URL",
                        f"https://mainnet.helius-rpc.com/?api-key={os.environ.get('HELIUS_API_KEY', 'bb6ff3e9-e38d-4362-9e7a-669a00d497a8')}",
                    )

                    # Initialize Solana program adapter
                    if HAS_SOLANA_ADAPTER:
                        try:
                            self.solana_adapter = SolanaProgramAdapter(
                                rpc_url=self.solana_rpc, private_key=solana_pk
                            )
                            logger.info(
                                "Solana program adapter initialized (direct program mode)"
                            )
                        except Exception as e:
                            logger.warning(f"Solana adapter init failed: {e}")
                except Exception as e:
                    logger.error(f"Solana wallet error: {e}")

            # Web3 for EVM
            if self.evm_account:
                self.w3 = self.get_web3()

                # Initialize contract executor for direct on-chain calls
                if HAS_CONTRACT_EXECUTOR and self.w3:
                    try:
                        self.contract_executor = ContractExecutor(
                            self.w3, self.evm_account
                        )
                        logger.info(
                            "Contract executor initialized (direct on-chain mode)"
                        )
                    except Exception as e:
                        logger.warning(f"Contract executor init failed: {e}")

            logger.info("DEX Aggregator Trader initialized")

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            raise

    def _refresh_sol_gas_reserve(self):
        """Calculate SOL gas reserve from live price: $0.15 USD worth of SOL."""
        try:
            resp = requests.get(
                "https://coins.llama.fi/prices/current/coingecko:solana",
                timeout=5,
            )
            sol_price = Decimal(str(resp.json()["coins"]["coingecko:solana"]["price"]))
            reserve = self._SOLANA_GAS_RESERVE_USD / sol_price
            # Floor at 0.0001 SOL to avoid dust issues
            self.SOLANA_GAS_RESERVE = max(reserve, Decimal("0.0001"))
            logger.info(
                f"SOL gas reserve: {self.SOLANA_GAS_RESERVE:.6f} SOL "
                f"(${self._SOLANA_GAS_RESERVE_USD} at ${sol_price}/SOL)"
            )
        except Exception as e:
            logger.warning(f"SOL price fetch failed, using fallback reserve: {e}")
            # Keep default fallback of 0.001 SOL

    # ==================== TRADE HISTORY ====================

    def _load_trade_history(self) -> dict:
        """Load trade history from disk. Tracks buys, sells, and failed attempts."""
        try:
            os.makedirs(os.path.dirname(self.TRADE_HISTORY_FILE), exist_ok=True)
            if os.path.exists(self.TRADE_HISTORY_FILE):
                with open(self.TRADE_HISTORY_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"buys": {}, "sells": {}, "failed": {}}

    def _save_trade_history(self):
        """Persist trade history to disk."""
        try:
            os.makedirs(os.path.dirname(self.TRADE_HISTORY_FILE), exist_ok=True)
            with open(self.TRADE_HISTORY_FILE, "w") as f:
                json.dump(self.trade_history, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save trade history: {e}")

    def record_buy(self, token: str, chain: str, address: str, amount: float):
        """Record a successful buy."""
        key = f"{chain}:{token}"
        self.trade_history["buys"][key] = {
            "token": token,
            "chain": chain,
            "address": address,
            "amount": amount,
            "timestamp": time.time(),
        }
        # Clear failed attempts on successful buy
        self.trade_history["failed"].pop(key, None)
        self._save_trade_history()
        logger.info(f"[History] Recorded BUY: {token} on {chain}")

    def record_sell(self, token: str, chain: str):
        """Record a successful sell."""
        key = f"{chain}:{token}"
        self.trade_history["sells"][key] = {
            "token": token,
            "chain": chain,
            "timestamp": time.time(),
        }
        # Remove from buys
        self.trade_history["buys"].pop(key, None)
        self._save_trade_history()
        logger.info(f"[History] Recorded SELL: {token} on {chain}")

    def record_failed_trade(self, token: str, chain: str, reason: str):
        """Record a failed trade attempt. After 3 failures, token is blacklisted for 1 hour."""
        key = f"{chain}:{token}"
        if key not in self.trade_history["failed"]:
            self.trade_history["failed"][key] = {
                "count": 0,
                "reasons": [],
                "first_fail": time.time(),
            }
        self.trade_history["failed"][key]["count"] += 1
        self.trade_history["failed"][key]["reasons"].append(reason[:80])
        self.trade_history["failed"][key]["last_fail"] = time.time()
        self._save_trade_history()

    def should_skip_token(self, token: str, chain: str) -> bool:
        """Check if a token should be skipped (failed 3+ times in last 6 hours)."""
        key = f"{chain}:{token}"
        failed = self.trade_history["failed"].get(key, {})
        count = failed.get("count", 0)
        last_fail = failed.get("last_fail", 0)

        # Reset failures older than 6 hours (was 1 hour - too aggressive)
        if last_fail and (time.time() - last_fail) > 21600:
            self.trade_history["failed"].pop(key, None)
            self._save_trade_history()
            return False

        # Skip if failed 3+ times
        if count >= 3:
            return True

        return False

    def is_already_held(self, token: str, chain: str) -> bool:
        """Check if we already hold this token (bought but not sold)."""
        key = f"{chain}:{token}"
        return key in self.trade_history["buys"]

    def _remove_stale_buy(self, token: str, chain: str, reason: str = ""):
        """Remove stale buy entries that no longer exist on-chain.

        This prevents repeated sell loops against positions that were already closed
        externally or never settled into wallet balance.
        """
        key = f"{chain}:{token}"
        if key in self.trade_history.get("buys", {}):
            self.trade_history["buys"].pop(key, None)
            self._save_trade_history()
            extra = f" ({reason})" if reason else ""
            logger.info(f"[History] Removed stale BUY: {token} on {chain}{extra}")

    def _prune_stale_active_positions(
        self, active_positions: Dict, holdings: Dict
    ) -> int:
        """Drop active positions that no longer have on-chain balance.

        Returns number of removed stale positions.
        """
        removed = 0
        sol_wallet = str(self.solana_keypair.pubkey()) if self.solana_keypair else ""

        for token, position in list(active_positions.items()):
            chain = position.get("chain", "base")
            token_addr = position.get("address", "")
            has_balance = False

            try:
                if chain == "base":
                    # Fast path: reuse already-fetched holdings snapshot
                    held = holdings.get(token)
                    if held and Decimal(str(held.get("balance", 0))) > Decimal("0"):
                        has_balance = True
                    elif token_addr and token_addr.startswith("0x"):
                        bal = self.get_token_balance(token_addr, "base")
                        has_balance = bal > Decimal("0")

                elif (
                    chain == "solana"
                    and self.solana_adapter
                    and sol_wallet
                    and token_addr
                ):
                    bal = self.solana_adapter.get_token_balance(token_addr, sol_wallet)
                    has_balance = bal > 0
            except Exception:
                has_balance = False

            if not has_balance:
                logger.info(
                    f"[Position Cleanup] Dropping stale {token} on {chain} (no on-chain balance)"
                )
                del active_positions[token]
                self._remove_stale_buy(token, chain, reason="no on-chain balance")
                removed += 1

        return removed

    def get_web3(self) -> Optional[Web3]:
        """Get Web3 connection."""
        rpcs = [
            f"https://base-mainnet.g.alchemy.com/v2/{os.environ.get('ALCHEMY_API_KEY', 'DbRpGYbLsNo-hOI40cfh8')}",
            "https://base.llamarpc.com",
            "https://base.drpc.org",
            "https://mainnet.base.org",
            f"https://bold-proportionate-dinghy.base-mainnet.quiknode.pro/{os.environ.get('QUICKNODE_KEY', 'QN_9a2d68943d664e7bb3a3966791bfb4b3')}",
        ]
        for rpc in rpcs:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
                if w3.is_connected():
                    return w3
            except:
                continue
        return None

    # ==================== JUPITER (Solana) ====================

    def jupiter_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Jupiter."""
        try:
            resp = requests.get(
                f"{self.JUPITER_API}/quote",
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(amount),
                    "slippageBps": slippage_bps,
                },
                headers={"x-api-key": self.JUPITER_API_KEY},
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"Jupiter quote error: {e}")
            return {}

    def jupiter_swap(self, quote: Dict, wallet: str) -> Dict:
        """Execute swap on Jupiter."""
        try:
            resp = requests.post(
                f"{self.JUPITER_API}/swap",
                json={
                    "quoteResponse": quote,
                    "userPublicKey": wallet,
                    "wrapAndUnwrapSol": True,
                },
                headers={"x-api-key": self.JUPITER_API_KEY},
                timeout=30,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"Jupiter swap error: {e}")
            return {}

    # ==================== KYBERSWAP (EVM) ====================

    def kyberswap_quote(
        self, chain: str, token_in: str, token_out: str, amount: str
    ) -> Dict:
        """Get quote from KyberSwap."""
        chain_ids = {
            "base": "base",
            "ethereum": "ethereum",
            "arbitrum": "arbitrum",
            "polygon": "polygon",
            "bsc": "bsc",
        }
        chain_id = chain_ids.get(chain, "base")
        try:
            resp = requests.get(
                f"{self.KYBERSWAP_API}/{chain_id}/api/v1/routes",
                params={
                    "tokenIn": token_in,
                    "tokenOut": token_out,
                    "amountIn": amount,
                },
                headers={"x-client-id": "hermes-bot"},
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"KyberSwap quote error: {e}")
            return {}

    def kyberswap_build(
        self, chain: str, route: Dict, sender: str, recipient: str, slippage: int = 50
    ) -> Dict:
        """Build swap transaction on KyberSwap (V1 API)."""
        chain_ids = {
            "base": "base",
            "ethereum": "ethereum",
            "arbitrum": "arbitrum",
            "polygon": "polygon",
            "bsc": "bsc",
        }
        chain_id = chain_ids.get(chain, "base")
        try:
            import time

            resp = requests.post(
                f"{self.KYBERSWAP_API}/{chain_id}/api/v1/route/build",
                json={
                    "routeSummary": route,
                    "sender": sender,
                    "recipient": recipient,
                    "slippageTolerance": slippage,
                    "deadline": int(time.time()) + 1800,
                    "source": "hermes-bot",
                },
                headers={"x-client-id": "hermes-bot"},
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"KyberSwap build error: {e}")
            return {}

    # ==================== LIFI (Multi-chain) ====================

    def lifi_quote(
        self,
        from_chain: str,
        to_chain: str,
        from_token: str,
        to_token: str,
        from_amount: str,
        from_address: str,
    ) -> Dict:
        """Get quote from LiFi."""
        try:
            resp = requests.get(
                f"{self.LIFI_API}/quote",
                params={
                    "fromChain": from_chain,
                    "toChain": to_chain,
                    "fromToken": from_token,
                    "toToken": to_token,
                    "fromAmount": from_amount,
                    "fromAddress": from_address,
                },
                headers={"x-lifi-api-key": self.LIFI_API_KEY},
                timeout=15,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"LiFi quote error: {e}")
            return {}

    def lifi_chains(self) -> List[Dict]:
        """Get supported chains from LiFi."""
        try:
            resp = requests.get(
                f"{self.LIFI_API}/chains",
                headers={"x-lifi-api-key": self.LIFI_API_KEY},
                timeout=10,
            )
            return resp.json().get("chains", [])
        except Exception as e:
            logger.error(f"LiFi chains error: {e}")
            return []

    # ==================== OPENOCEAN (Multi-chain) ====================

    def openocean_quote(
        self,
        chain: str,
        in_token: str,
        out_token: str,
        amount: str,
        gas_price: str = None,
    ) -> Dict:
        """Get quote from OpenOcean using realtime gas when possible."""
        chain_ids = {
            "base": 8453,
            "ethereum": 1,
            "arbitrum": 42161,
            "polygon": 137,
            "bsc": 56,
            "solana": 101,
        }
        chain_id = chain_ids.get(chain, 8453)

        if gas_price is None:
            try:
                # OpenOcean expects gwei string on EVM chains
                live_gwei = (self.w3.eth.gas_price / 1e9) if self.w3 else 1.0
                gas_price = f"{max(live_gwei, 0.001):.6f}"
            except Exception:
                gas_price = "0.001000"

        try:
            resp = requests.get(
                f"{self.OPENOCEAN_API}/{chain_id}/quote",
                params={
                    "inTokenAddress": in_token,
                    "outTokenAddress": out_token,
                    "amount": amount,
                    "gasPrice": gas_price,
                },
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"OpenOcean quote error: {e}")
            return {}

    # ==================== VELORA/PARASWAP (EVM) ====================

    def velora_quote(
        self,
        chain: int,
        src_token: str,
        dest_token: str,
        amount: str,
        src_decimals: int = 18,
        dest_decimals: int = 18,
    ) -> Dict:
        """Get quote from Velora (ParaSwap)."""
        try:
            resp = requests.get(
                f"{self.VELORA_API}/prices",
                params={
                    "srcToken": src_token,
                    "destToken": dest_token,
                    "amount": amount,
                    "srcDecimals": src_decimals,
                    "destDecimals": dest_decimals,
                    "network": chain,
                    "version": 6.2,
                },
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"Velora quote error: {e}")
            return {}

    # ==================== PORTALS.FI ====================

    def portals_quote(
        self, chain: str, token_in: str, token_out: str, amount: str
    ) -> Dict:
        """Get quote from Portals.fi."""
        chain_ids = {
            "base": 8453,
            "ethereum": 1,
            "arbitrum": 42161,
            "polygon": 137,
            "bsc": 56,
            "solana": "solana",
        }
        chain_id = chain_ids.get(chain, 8453)

        try:
            headers = {"Authorization": f"Bearer {self.PORTALS_BEARER}"}
            resp = requests.get(
                f"{self.PORTALS_API}/quote",
                params={
                    "chainId": chain_id,
                    "tokenIn": token_in,
                    "tokenOut": token_out,
                    "amountIn": amount,
                },
                headers=headers,
                timeout=15,
            )

            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Portals.fi quote error: {e}")
        return {}

    # ==================== ENSO BUILD ====================

    def enso_quote(
        self, chain: str, token_in: str, token_out: str, amount: str
    ) -> Dict:
        """Get quote from Enso Build API."""
        chain_ids = {
            "base": 8453,
            "ethereum": 1,
            "arbitrum": 42161,
            "polygon": 137,
            "bsc": 56,
        }
        chain_id = chain_ids.get(chain, 8453)

        try:
            resp = requests.get(
                f"{self.ENSO_API}/route",
                params={
                    "chainId": chain_id,
                    "tokenIn": token_in,
                    "tokenOut": token_out,
                    "amountIn": amount,
                },
                timeout=15,
            )

            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Enso quote error: {e}")
        return {}

    # ==================== ODOS (EVM) ====================

    def odos_quote(
        self, chain: str, token_in: str, token_out: str, amount: str, wallet: str = ""
    ) -> Dict:
        """Get quote from Odos."""
        chain_ids = {
            "base": 8453,
            "ethereum": 1,
            "arbitrum": 42161,
            "polygon": 137,
            "bsc": 56,
        }
        chain_id = chain_ids.get(chain, 8453)
        if not wallet:
            wallet = self.evm_account.address if self.evm_account else ""

        try:
            resp = requests.post(
                f"{self.ODOS_API}/sor/quote/v2",
                json={
                    "chainId": chain_id,
                    "inputTokens": [{"tokenAddress": token_in, "amount": amount}],
                    "outputTokens": [{"tokenAddress": token_out, "proportion": 1}],
                    "userAddr": wallet,
                    "slippageLimitPercent": 0.3,
                    "compact": True,
                },
                timeout=15,
            )

            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Odos quote error: {e}")
        return {}

    def odos_assemble(self, path_id: str, wallet: str = "") -> Dict:
        """Assemble Odos transaction from path ID."""
        if not wallet:
            wallet = self.evm_account.address if self.evm_account else ""
        try:
            resp = requests.post(
                f"{self.ODOS_API}/sor/assemble",
                json={
                    "pathId": path_id,
                    "simulate": False,
                    "userAddr": wallet,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Odos assemble error: {e}")
        return {}

    # ==================== COW PROTOCOL (Base) ====================

    def cow_quote(self, token_in: str, token_out: str, amount: str) -> Dict:
        """Get quote from CoW Protocol (Base). Uses sellAmountBeforeFee."""
        try:
            resp = requests.post(
                f"{self.COW_API}/api/v1/quote",
                json={
                    "sellToken": token_in,
                    "buyToken": token_out,
                    "sellAmountBeforeFee": amount,
                    "from": self.evm_account.address if self.evm_account else "",
                    "receiver": self.evm_account.address if self.evm_account else "",
                    "validTo": int(time.time()) + 1800,
                    "appData": "0x0000000000000000000000000000000000000000000000000000000000000000",
                    "partiallyFillable": False,
                    "sellTokenBalance": "erc20",
                    "buyTokenBalance": "erc20",
                    "kind": "sell",
                    "signingScheme": "eip712",
                },
                headers={"Content-Type": "application/json"},
                timeout=15,
            )

            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"CoW quote error: {e}")
        return {}

    # ==================== RAYDIUM (Solana) ====================

    def raydium_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Raydium (Solana)."""
        try:
            resp = requests.get(
                f"{self.RAYDIUM_API}/compute/swap-base-in",
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

    # ==================== JUPITER V1 API ====================

    def jupiter_v1_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict:
        """Get quote from Jupiter v1 API (fallback when v6 blocked)."""
        try:
            resp = requests.get(
                f"{self.JUPITER_API_V1}/quote",
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
            logger.error(f"Jupiter v1 quote error: {e}")
        return {}

    # ==================== OKU TRADE ====================

    def oku_quote(self, chain: str, token_in: str, token_out: str, amount: str) -> Dict:
        """Get quote from Oku Trade API."""
        chain_names = {
            "base": "base",
            "ethereum": "ethereum",
            "arbitrum": "arbitrum",
            "polygon": "polygon",
            "bsc": "bsc",
        }
        chain_name = chain_names.get(chain, "base")

        try:
            resp = requests.get(
                f"{self.OKU_API}/{chain_name}/quote",
                params={
                    "tokenIn": token_in,
                    "tokenOut": token_out,
                    "amount": amount,
                },
                timeout=15,
            )

            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Oku quote error: {e}")
        return {}

    # ==================== BALANCE CHECKS ====================

    def get_token_address(self, symbol: str, chain: str) -> Optional[str]:
        """Get token address from symbol. Uses screener's top100.json for Base tokens."""
        # Utility/static tokens (always needed, not from screener)
        STATIC_TOKENS = {
            "base": {
                "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "WETH": "0x4200000000000000000000000000000000000006",
            },
            "solana": {
                "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
                "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
                "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
                "MYRO": "HhJpBhRRn4g56VsyTuTMEjY2rLxMy8R3kXezvJcVNqFQ",
                "SILLY": "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV3qyouov87awMs",
                "SMOG": "FS66vFbZmq8r4GKoF7PqZf7mVz1kLTsZ7gZpFLhR5sMh",
            },
        }

        # Check static first (fast, no IO)
        chain_static = STATIC_TOKENS.get(chain, {})
        if symbol.upper() in chain_static:
            return chain_static[symbol.upper()]

        # For Base: load from screener
        if chain == "base":
            screener_tokens = self._load_screener_tokens()
            if symbol.upper() in screener_tokens:
                return screener_tokens[symbol.upper()]

        # Return the symbol itself if it looks like an address
        if chain == "base" and symbol.startswith("0x") and len(symbol) == 42:
            return symbol
        elif chain == "solana" and len(symbol) > 30:
            return symbol

        return None

    def get_balance(self, chain: str) -> Decimal:
        """Get native balance with RPC rotation."""
        if chain == "base" and self.evm_account:
            rpcs = [
                "https://mainnet.base.org",
                "https://base.llamarpc.com",
                "https://base.drpc.org",
                "https://1rpc.io/base",
                "https://base.meowrpc.com",
                f"https://base-mainnet.g.alchemy.com/v2/{os.environ.get('ALCHEMY_API_KEY', 'DbRpGYbLsNo-hOI40cfh8')}",
                f"https://bold-proportionate-dinghy.base-mainnet.quiknode.pro/{os.environ.get('QUICKNODE_KEY', 'QN_9a2d68943d664e7bb3a3966791bfb4b3')}",
                "https://rpc.ankr.com/base/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792",
            ]
            for rpc_url in rpcs:
                try:
                    w3 = Web3(
                        Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10})
                    )
                    bal = w3.eth.get_balance(self.evm_account.address)
                    return Decimal(bal) / Decimal(1e18)
                except Exception:
                    continue
            logger.error("All Base RPCs failed for balance check")
        elif chain == "solana" and self.solana_keypair:
            try:
                rpc = getattr(
                    self,
                    "solana_rpc",
                    os.environ.get(
                        "SOLANA_RPC_URL",
                        f"https://mainnet.helius-rpc.com/?api-key={os.environ.get('HELIUS_API_KEY', 'bb6ff3e9-e38d-4362-9e7a-669a00d497a8')}",
                    ),
                )
                resp = requests.post(
                    rpc,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getBalance",
                        "params": [str(self.solana_keypair.pubkey())],
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if "result" in data:
                        return Decimal(data["result"]["value"]) / Decimal(1e9)
            except Exception as e:
                logger.error(f"Solana balance error: {e}")
        return Decimal("0")

    def _base_rpcs(self) -> List[str]:
        return [
            "https://mainnet.base.org",
            "https://base.llamarpc.com",
            "https://base.drpc.org",
            "https://1rpc.io/base",
            "https://base.meowrpc.com",
            f"https://base-mainnet.g.alchemy.com/v2/{os.environ.get('ALCHEMY_API_KEY', 'DbRpGYbLsNo-hOI40cfh8')}",
            f"https://bold-proportionate-dinghy.base-mainnet.quiknode.pro/{os.environ.get('QUICKNODE_KEY', 'QN_9a2d68943d664e7bb3a3966791bfb4b3')}",
            "https://rpc.ankr.com/base/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792",
        ]

    def get_token_decimals(self, token_address: str, chain: str = "base") -> int:
        """Get ERC20 decimals with RPC rotation."""
        if chain != "base":
            return 18

        abi = [
            {
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "stateMutability": "view",
                "type": "function",
            }
        ]

        for rpc_url in self._base_rpcs():
            try:
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                if not w3.is_connected():
                    continue
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(token_address), abi=abi
                )
                return int(contract.functions.decimals().call())
            except Exception:
                continue

        return 18

    def get_token_balance(self, token_address: str, chain: str = "base") -> Decimal:
        """Get ERC20 token balance on EVM chain with RPC rotation."""
        if chain != "base" or not self.evm_account:
            return Decimal("0")

        abi = [
            {
                "inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]

        for rpc_url in self._base_rpcs():
            try:
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                if not w3.is_connected():
                    continue
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(token_address), abi=abi
                )
                raw = contract.functions.balanceOf(self.evm_account.address).call()
                try:
                    decimals = int(contract.functions.decimals().call())
                except Exception:
                    decimals = 18
                return Decimal(raw) / Decimal(10**decimals)
            except Exception:
                continue

        logger.error(f"All RPCs failed for token balance: {token_address}")
        return Decimal("0")

    def _load_screener_tokens(self) -> Dict[str, str]:
        """Load top-scoring Base tokens from the screener's top100.json."""
        screener_path = os.path.expanduser("~/.hermes/data/token_screener/top100.json")
        tokens = {}
        try:
            with open(screener_path, "r") as f:
                data = json.load(f)
            for t in data.get("top_tokens", data.get("tokens", [])):
                if t.get("chain") != "base":
                    continue
                addr = t.get("contract_address") or t.get("address") or ""
                sym = t.get("symbol") or t.get("name") or "UNKNOWN"
                score = t.get("score") or t.get("priority_score") or 0
                if addr and score >= 20:  # Only tokens with decent screener score
                    tokens[sym] = addr
            logger.info(f"Loaded {len(tokens)} Base tokens from screener (top100.json)")
        except Exception as e:
            logger.warning(f"Failed to load screener tokens: {e}")
        return tokens

    def _discover_wallet_tokens(self) -> Dict[str, str]:
        """Discover Base tokens the wallet actually holds by checking known token list + on-chain."""
        tokens = {}
        # Expanded list of popular Base tokens to check (updated regularly from Dexscreener)
        # This is NOT for trading decisions - just for discovering what we already hold
        KNOWN_BASE_TOKENS = {
            "BRETT": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
            "DEGEN": "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed",
            "TOSHI": "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4",
            "HIGHER": "0x0578d8A44db98B23BF096A382e016e29a5Ce0ffe",
            "NORMIE": "0x7F12d13B34F5F4f0a9449c16Bcd42f0da47AF200",
            "TYBG": "0x0d97F261b1e88845184f678e2d1e7a98D9FD38dE",
            "BRIAN": "0x22af33fe49fd1fa80c7149773dde5890d3c76f3b",
            "BALD": "0x27D2DECb4bFC9C76F0309b8E88dec3a601Fe25a8",
            "ROCKY": "0x2Da56AcB9Ea78330f947bD57C54119Debda7AF71",
        }
        for sym, addr in KNOWN_BASE_TOKENS.items():
            bal = self.get_token_balance(addr, "base")
            if bal > Decimal("0.001"):
                tokens[sym] = addr
        if tokens:
            logger.info(
                f"Discovered {len(tokens)} held Base tokens: {', '.join(tokens.keys())}"
            )
        return tokens

    def get_all_holdings(self) -> Dict:
        """Get all token holdings on Base - checks screener tokens + wallet discovery + WETH."""
        holdings = {}

        # 1. Tokens from screener pipeline (highest priority - scored)
        screener_tokens = self._load_screener_tokens()

        # 2. Optional wallet discovery scan (expensive) with cache/interval guard
        wallet_tokens = {}
        if self.wallet_discovery_enabled:
            now = time.time()
            if now - self._last_wallet_discovery_ts >= max(
                30, self.wallet_discovery_interval_sec
            ):
                logger.info("Running wallet token discovery scan (cached mode)")
                self._cached_wallet_tokens = self._discover_wallet_tokens()
                self._last_wallet_discovery_ts = now
            wallet_tokens = dict(self._cached_wallet_tokens)

        # Merge: screener takes priority for naming, wallet fills gaps
        all_tokens = {**wallet_tokens, **screener_tokens}

        for name, addr in all_tokens.items():
            bal = self.get_token_balance(addr, "base")
            if bal > Decimal("0.001"):
                holdings[name] = {"address": addr, "balance": bal}

        # Always check WETH (needed for unwrapping)
        weth_bal = self.get_token_balance(
            "0x4200000000000000000000000000000000000006", "base"
        )
        if weth_bal > Decimal("0.00001"):
            holdings["WETH"] = {
                "address": "0x4200000000000000000000000000000000000006",
                "balance": weth_bal,
            }

        return holdings

    def _unwrap_weth(self, amount: Decimal) -> bool:
        """Unwrap WETH to ETH on Base."""
        if not self.w3 or not self.evm_account:
            return False
        try:
            weth_addr = Web3.to_checksum_address(
                "0x4200000000000000000000000000000000000006"
            )
            weth_abi = [
                {
                    "inputs": [{"name": "wad", "type": "uint256"}],
                    "name": "withdraw",
                    "outputs": [],
                    "stateMutability": "nonpayable",
                    "type": "function",
                },
                {
                    "inputs": [{"name": "", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                },
            ]
            contract = self.w3.eth.contract(address=weth_addr, abi=weth_abi)
            amount_wei = int(amount * Decimal(10**18))
            tx = contract.functions.withdraw(amount_wei).build_transaction(
                {
                    "from": self.evm_account.address,
                    "nonce": self.w3.eth.get_transaction_count(
                        self.evm_account.address, "pending"
                    ),
                    "gas": 35000,
                    "maxFeePerGas": self.w3.eth.gas_price,
                    "maxPriorityFeePerGas": self.w3.eth.max_priority_fee,
                    "chainId": 8453,
                }
            )
            signed = self.evm_account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            logger.info(f"WETH unwrap tx sent: {tx_hash.hex()}")
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status == 1:
                logger.info(f"WETH unwrap confirmed: {tx_hash.hex()}")
                return True
            else:
                logger.error(f"WETH unwrap failed: {tx_hash.hex()}")
                return False
        except Exception as e:
            logger.error(f"WETH unwrap error: {e}")
            return False

    def _sell_via_kyberswap(
        self, token_name: str, token_address: str, sell_amount: Decimal
    ) -> bool:
        """Fallback sell via KyberSwap when Odos fails."""
        try:
            token_decimals = self.get_token_decimals(token_address, "base")
            amount_wei = str(int(sell_amount * Decimal(10**token_decimals)))
            weth = "0x4200000000000000000000000000000000000006"

            # Get KyberSwap quote via GET (V1 API uses GET with query params)
            quote_url = f"https://aggregator-api.kyberswap.com/base/api/v1/routes"
            quote_resp = requests.get(
                quote_url,
                params={
                    "tokenIn": token_address,
                    "tokenOut": weth,
                    "amountIn": amount_wei,
                },
                headers={"x-client-id": "hermes-bot"},
                timeout=15,
            )

            if quote_resp.status_code != 200:
                logger.error(f"KyberSwap quote failed: {quote_resp.status_code}")
                return False

            quote_json = quote_resp.json()
            if quote_json.get("code", -1) != 0:
                logger.error(
                    f"KyberSwap quote error: {quote_json.get('message', 'Unknown')}"
                )
                return False

            route_data = quote_json.get("data", {})

            # Build swap transaction FIRST (V1 API: router address only in build response)
            build_resp = requests.post(
                "https://aggregator-api.kyberswap.com/base/api/v1/route/build",
                json={
                    "routeSummary": route_data.get("routeSummary"),
                    "sender": self.evm_account.address,
                    "recipient": self.evm_account.address,
                    "slippageTolerance": 500,
                    "deadline": int(time.time()) + 1800,
                    "source": "hermes-bot",
                },
                headers={"x-client-id": "hermes-bot"},
                timeout=15,
            )

            if build_resp.status_code != 200:
                logger.error(f"KyberSwap build failed: {build_resp.status_code}")
                return False

            build_json = build_resp.json()
            if build_json.get("code", -1) != 0:
                logger.error(
                    f"KyberSwap build error: {build_json.get('message', 'Unknown')}"
                )
                return False

            tx_data = build_json.get("data", {})
            router_address = tx_data.get("routerAddress")

            # Approve KyberSwap router (now that we have router address)
            if router_address and not self._erc20_approve_if_needed(
                token_address, router_address, int(amount_wei)
            ):
                logger.error(f"Failed to approve {token_name} for KyberSwap")
                return False

            tx = {
                "from": self.evm_account.address,
                "to": Web3.to_checksum_address(
                    tx_data.get("routerAddress", router_address)
                ),
                "data": tx_data.get("data"),
                "value": 0,  # ERC20 sell: no native ETH value
                "gas": int(tx_data.get("gas", 300000)),
                "maxFeePerGas": self.w3.eth.gas_price,
                "maxPriorityFeePerGas": self.w3.eth.max_priority_fee,
                "nonce": self.w3.eth.get_transaction_count(
                    self.evm_account.address, "pending"
                ),
                "chainId": 8453,
            }

            signed = self.evm_account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            logger.info(f"KyberSwap sell sent: {tx_hash.hex()}")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 1:
                logger.info(
                    f"KyberSwap sell confirmed: {token_name} -> WETH | tx: {tx_hash.hex()}"
                )
                return True
            else:
                logger.error(f"KyberSwap sell failed: {tx_hash.hex()}")
                return False

        except Exception as e:
            logger.error(f"KyberSwap sell error: {e}")
            import traceback

            traceback.print_exc()
            return False

    def _sell_via_velora(
        self, token_name: str, token_address: str, sell_amount: Decimal
    ) -> bool:
        """Sell via Velora (ParaSwap) API."""
        try:
            token_decimals = self.get_token_decimals(token_address, "base")
            amount_wei = str(int(sell_amount * Decimal(10**token_decimals)))
            weth = "0x4200000000000000000000000000000000000006"

            # Get price quote
            price_resp = requests.get(
                f"{self.VELORA_API}/prices",
                params={
                    "srcToken": token_address,
                    "destToken": weth,
                    "amount": amount_wei,
                    "srcDecimals": token_decimals,
                    "destDecimals": 18,
                    "network": 8453,
                    "version": 6.2,
                },
                timeout=15,
            )

            if price_resp.status_code != 200:
                logger.error(
                    f"Velora quote failed: {price_resp.status_code} - {price_resp.text[:200]}"
                )
                return False

            price_data = price_resp.json()
            if "priceRoute" not in price_data:
                logger.error("Velora: no priceRoute in response")
                return False

            dest_amount = price_data["priceRoute"].get("destAmount", "0")
            if int(dest_amount) == 0:
                logger.error("Velora: zero output amount")
                return False

            logger.info(
                f"Velora quote: {sell_amount} {token_name} -> {int(dest_amount)/1e18:.8f} WETH"
            )

            # Build transaction
            build_resp = requests.post(
                f"{self.VELORA_API}/transactions/8453",
                json={
                    "priceRoute": price_data["priceRoute"],
                    "srcToken": token_address,
                    "destToken": weth,
                    "srcAmount": amount_wei,
                    "destAmount": dest_amount,
                    "userAddress": self.evm_account.address,
                    "partner": "hermes-bot",
                },
                params={"ignoreChecks": "true"},
                timeout=15,
            )

            if build_resp.status_code != 200:
                logger.error(f"Velora build failed: {build_resp.status_code}")
                return False

            tx_data = build_resp.json()

            # Approve token spending
            if not self._erc20_approve_if_needed(
                token_address, tx_data.get("to", ""), int(amount_wei)
            ):
                logger.error(f"Failed to approve {token_name} for Velora router")
                return False

            # Send transaction
            tx = {
                "from": self.evm_account.address,
                "to": Web3.to_checksum_address(tx_data.get("to")),
                "data": tx_data.get("data"),
                "value": int(tx_data.get("value", "0")),
                "gas": int(tx_data.get("gas", 300000)),
                "maxFeePerGas": self.w3.eth.gas_price,
                "maxPriorityFeePerGas": self.w3.eth.max_priority_fee,
                "nonce": self.w3.eth.get_transaction_count(
                    self.evm_account.address, "pending"
                ),
                "chainId": 8453,
            }

            signed = self.evm_account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            logger.info(f"Velora sell sent: {tx_hash.hex()}")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 1:
                logger.info(
                    f"Velora sell confirmed: {token_name} -> WETH | tx: {tx_hash.hex()}"
                )
                return True
            else:
                logger.error(f"Velora sell failed: {tx_hash.hex()}")
                return False

        except Exception as e:
            logger.error(f"Velora sell error: {e}")
            import traceback

            traceback.print_exc()
            return False

    def _get_web3(self) -> Web3:
        """Get a fresh Web3 connection from the RPC rotation pool."""
        for rpc_url in self._base_rpcs():
            try:
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                if w3.is_connected():
                    return w3
            except Exception:
                continue
        return self.w3  # Fallback to main

    def _erc20_approve_if_needed(
        self, token_address: str, spender: str, amount_wei: int
    ) -> bool:
        """Approve ERC20 token spending if allowance is insufficient. Returns True on success."""
        if not self.w3 or not self.evm_account:
            return False
        try:
            erc20_abi = [
                {
                    "inputs": [
                        {"name": "owner", "type": "address"},
                        {"name": "spender", "type": "address"},
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                },
                {
                    "inputs": [
                        {"name": "spender", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                    ],
                    "name": "approve",
                    "outputs": [{"name": "", "type": "bool"}],
                    "stateMutability": "nonpayable",
                    "type": "function",
                },
            ]
            # Use rotating RPC for reads to avoid rate limits
            read_w3 = self._get_web3()
            token_contract = read_w3.eth.contract(
                address=Web3.to_checksum_address(token_address), abi=erc20_abi
            )
            current_allowance = token_contract.functions.allowance(
                self.evm_account.address, Web3.to_checksum_address(spender)
            ).call()
            if current_allowance >= amount_wei:
                logger.info(
                    f"Allowance sufficient: {current_allowance} >= {amount_wei}"
                )
                return True
            # Approve max uint256
            MAX_UINT256 = 2**256 - 1
            # Use main w3 for writes (send tx), but get gas from live
            gas_price = self.w3.eth.gas_price
            approve_fn = token_contract.functions.approve(
                Web3.to_checksum_address(spender), MAX_UINT256
            )
            approve_data = approve_fn._encode_transaction_data()
            tx = {
                "from": self.evm_account.address,
                "to": Web3.to_checksum_address(token_address),
                "data": approve_data,
                "value": 0,
                "gas": 60000,
                "nonce": self.w3.eth.get_transaction_count(
                    self.evm_account.address, "pending"
                ),
                "maxFeePerGas": gas_price,
                "maxPriorityFeePerGas": max(gas_price // 10, 10000),
                "chainId": 8453,
            }
            signed = self.evm_account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            logger.info(f"Approve tx sent: {tx_hash.hex()}")
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status == 1:
                logger.info(f"Approve confirmed: {tx_hash.hex()}")
                return True
            else:
                logger.error(f"Approve failed: {tx_hash.hex()}")
                return False
        except Exception as e:
            logger.error(f"Approve error: {e}")
            return False

    def _direct_cheap_sell(self, token_address: str, amount_wei: int) -> Optional[str]:
        """Try direct on-chain swaps through cheapest AMM routers. Skips simulation to save gas.
        Uses actual router addresses from protocol_registry."""
        if not self.w3 or not self.evm_account:
            return None

        weth = "0x4200000000000000000000000000000000000006"
        addr = self.evm_account.address
        deadline = int(time.time()) + 300
        _live_gas = self.w3.eth.gas_price if self.w3 else 1_000_000  # 0.001 gwei
        cheap_gas = {
            "maxFeePerGas": max(_live_gas, 1_000_000),  # live gas, min 0.001 gwei
            "maxPriorityFeePerGas": max(_live_gas // 10, 100000),
            "chainId": 8453,
        }

        # ERC20 approve
        erc20_abi = [
            {
                "inputs": [
                    {"name": "spender", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "stateMutability": "nonpayable",
                "type": "function",
            },
            {
                "inputs": [
                    {"name": "owner", "type": "address"},
                    {"name": "spender", "type": "address"},
                ],
                "name": "allowance",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]
        token_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address), abi=erc20_abi
        )

        def ensure_allowance(spender: str):
            current = token_contract.functions.allowance(
                addr, Web3.to_checksum_address(spender)
            ).call()
            if current < amount_wei:
                approve_fn = token_contract.functions.approve(
                    Web3.to_checksum_address(spender), 2**256 - 1
                )
                approve_data = approve_fn._encode_transaction_data()
                approve_tx = {
                    "from": addr,
                    "to": Web3.to_checksum_address(token_address),
                    "data": approve_data,
                    "value": 0,
                    "gas": 60000,
                    "nonce": self.w3.eth.get_transaction_count(addr, "pending"),
                    **cheap_gas,
                }
                signed = self.evm_account.sign_transaction(approve_tx)
                txh = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(txh, timeout=60)
                if receipt.status != 1:
                    raise Exception(f"Approve failed: {txh.hex()}")

        def send_and_confirm(name: str, tx: dict) -> Optional[str]:
            signed = self.evm_account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            logger.info(f"{name} sell tx sent: {tx_hash.hex()}")
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 1 and receipt.gasUsed > 50000:
                logger.info(
                    f"{name} sell CONFIRMED: {tx_hash.hex()} (gas: {receipt.gasUsed})"
                )
                return tx_hash.hex()
            elif receipt.status == 1:
                logger.warning(
                    f"{name} tx succeeded but gas too low ({receipt.gasUsed}) - likely approve only, not swap"
                )
            else:
                logger.warning(
                    f"{name} sell reverted: {tx_hash.hex()} (gas: {receipt.gasUsed})"
                )
            return None

        # Load router addresses from contract_executor's protocol registry
        try:
            from protocol_registry import PROTOCOL_REGISTRY

            base_protocols = PROTOCOL_REGISTRY.get("base", {})
        except:
            base_protocols = {}

        # SushiSwap RouteProcessor4 (processRoute)
        sushi_cfg = base_protocols.get("sushiswap", {})
        sushi_router = sushi_cfg.get(
            "router", "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891"
        )
        sushi_abi = [
            {
                "inputs": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "to", "type": "address"},
                    {"name": "route", "type": "bytes"},
                ],
                "name": "processRoute",
                "outputs": [{"name": "amountOut", "type": "uint256"}],
                "stateMutability": "payable",
                "type": "function",
            }
        ]
        try:
            ensure_allowance(sushi_router)
            router = self.w3.eth.contract(
                address=Web3.to_checksum_address(sushi_router), abi=sushi_abi
            )
            fn = router.functions.processRoute(
                Web3.to_checksum_address(token_address),
                amount_wei,
                Web3.to_checksum_address(weth),
                0,
                Web3.to_checksum_address(addr),
                b"",
            )
            tx = {
                "from": addr,
                "to": Web3.to_checksum_address(sushi_router),
                "data": fn._encode_transaction_data(),
                "value": 0,
                "gas": 300000,
                "nonce": self.w3.eth.get_transaction_count(addr, "pending"),
                **cheap_gas,
            }
            result = send_and_confirm("SushiSwap", tx)
            if result:
                return result
        except Exception as e:
            logger.warning(f"SushiSwap sell failed: {str(e)[:120]}")

        # PancakeSwap V2 (swapExactTokensForTokens)
        pancake_cfg = base_protocols.get("pancakeswap", {})
        pancake_v2 = pancake_cfg.get(
            "router", "0x678Aa4bF4E210cf2166753e054d5b7c31cc7fa86"
        )
        V2_ABI = [
            {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                ],
                "name": "swapExactTokensForTokens",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function",
            }
        ]
        try:
            ensure_allowance(pancake_v2)
            router = self.w3.eth.contract(
                address=Web3.to_checksum_address(pancake_v2), abi=V2_ABI
            )
            fn = router.functions.swapExactTokensForTokens(
                amount_wei,
                0,
                [
                    Web3.to_checksum_address(token_address),
                    Web3.to_checksum_address(weth),
                ],
                Web3.to_checksum_address(addr),
                deadline,
            )
            tx = {
                "from": addr,
                "to": Web3.to_checksum_address(pancake_v2),
                "data": fn._encode_transaction_data(),
                "value": 0,
                "gas": 200000,
                "nonce": self.w3.eth.get_transaction_count(addr, "pending"),
                **cheap_gas,
            }
            result = send_and_confirm("PancakeV2", tx)
            if result:
                return result
        except Exception as e:
            logger.warning(f"PancakeV2 sell failed: {str(e)[:100]}")

        # Aerodrome swapExactTokensForETH - raw calldata with correct selector
        # Selector 0x18a13086 for swapExactTokensForETH(uint256,uint256,(address,address,bool)[],address,uint256)
        aero_router_addr = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
        try:
            ensure_allowance(aero_router_addr)
            deadline_ts = int(time.time()) + 1200

            # Build calldata: selector(4) + 5*32 bytes fixed + dynamic array
            sel = bytes.fromhex("18a13086")
            # Fixed params
            amount_enc = amount_wei.to_bytes(32, "big")
            min_out_enc = (0).to_bytes(32, "big")
            array_offset = (5 * 32).to_bytes(32, "big")  # 0xa0
            to_enc = bytes.fromhex(addr[2:].lower().zfill(64))
            deadline_enc = deadline_ts.to_bytes(32, "big")
            # Dynamic: Route[] with 1 element, 3 fields each
            array_len = (1).to_bytes(32, "big")
            from_enc = bytes.fromhex(token_address[2:].lower().zfill(64))
            weth_enc = bytes.fromhex(weth[2:].lower().zfill(64))
            stable_enc = (0).to_bytes(32, "big")

            calldata = (
                sel
                + amount_enc
                + min_out_enc
                + array_offset
                + to_enc
                + deadline_enc
                + array_len
                + from_enc
                + weth_enc
                + stable_enc
            )

            nonce = self.w3.eth.get_transaction_count(addr, "pending")
            tx = {
                "from": addr,
                "to": Web3.to_checksum_address(aero_router_addr),
                "data": calldata,
                "value": 0,
                "gas": 300000,
                "nonce": nonce,
                **cheap_gas,
            }
            result = send_and_confirm("Aerodrome", tx)
            if result:
                return result
        except Exception as e:
            logger.warning(f"Aerodrome swap failed: {str(e)[:120]}")

        # Try Aerodrome via processRoute (SushiRouteProcessor-compatible interface)
        sushi_router = sushi_cfg.get(
            "router", "0x0389879e0156033202C44BF784ac18fC02edeE4f"
        )
        try:
            ensure_allowance(sushi_router)
            router = self.w3.eth.contract(
                address=Web3.to_checksum_address(sushi_router), abi=sushi_abi
            )
            # Build actual route: encode pool address for auto-routing
            # SushiSwap processRoute needs route bytes for non-standard tokens
            fn = router.functions.processRoute(
                Web3.to_checksum_address(token_address),
                amount_wei,
                Web3.to_checksum_address(weth),
                0,
                Web3.to_checksum_address(addr),
                b"",
            )
            tx = {
                "from": addr,
                "to": Web3.to_checksum_address(sushi_router),
                "data": fn._encode_transaction_data(),
                "value": 0,
                "gas": 300000,
                "nonce": self.w3.eth.get_transaction_count(addr, "pending"),
                **cheap_gas,
            }
            result = send_and_confirm("SushiSwap", tx)
            if result:
                return result
        except Exception as e:
            logger.warning(f"SushiSwap sell failed: {str(e)[:120]}")

        # PancakeSwap V3 / Uniswap V3 (exactInputSingle)
        V3_ABI = [
            {
                "inputs": [
                    {
                        "components": [
                            {"name": "tokenIn", "type": "address"},
                            {"name": "tokenOut", "type": "address"},
                            {"name": "fee", "type": "uint24"},
                            {"name": "recipient", "type": "address"},
                            {"name": "deadline", "type": "uint256"},
                            {"name": "amountIn", "type": "uint256"},
                            {"name": "amountOutMinimum", "type": "uint256"},
                            {"name": "sqrtPriceLimitX96", "type": "uint160"},
                        ],
                        "name": "params",
                        "type": "tuple",
                    }
                ],
                "name": "exactInputSingle",
                "outputs": [{"name": "amountOut", "type": "uint256"}],
                "stateMutability": "payable",
                "type": "function",
            }
        ]
        for fee in [500, 2500, 3000, 10000]:
            try:
                ensure_allowance(
                    pancake_cfg.get(
                        "v3_router", "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4"
                    )
                )
                router = self.w3.eth.contract(
                    address=Web3.to_checksum_address(
                        pancake_cfg.get(
                            "v3_router", "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4"
                        )
                    ),
                    abi=V3_ABI,
                )
                params = (
                    Web3.to_checksum_address(token_address),
                    Web3.to_checksum_address(weth),
                    fee,
                    Web3.to_checksum_address(addr),
                    deadline,
                    amount_wei,
                    0,
                    0,
                )
                v3_router = pancake_cfg.get(
                    "v3_router", "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4"
                )
                fn = router.functions.exactInputSingle(params)
                tx = {
                    "from": addr,
                    "to": Web3.to_checksum_address(v3_router),
                    "data": fn._encode_transaction_data(),
                    "value": 0,
                    "gas": 250000,
                    "nonce": self.w3.eth.get_transaction_count(addr, "pending"),
                    **cheap_gas,
                }
                result = send_and_confirm(f"PancakeV3-{fee}", tx)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"PancakeV3-{fee} sell failed: {str(e)[:100]}")

        # Uniswap V3 (exactInputSingle) - multiple fee tiers
        uni_cfg = base_protocols.get("uniswap_v3", {})
        uni_router = uni_cfg.get("router", "0x2626664c2603336E57B271c5C0b26F421741e481")
        for fee in [100, 500, 3000, 10000]:
            try:
                ensure_allowance(uni_router)
                router = self.w3.eth.contract(
                    address=Web3.to_checksum_address(uni_router), abi=V3_ABI
                )
                params = (
                    Web3.to_checksum_address(token_address),
                    Web3.to_checksum_address(weth),
                    fee,
                    Web3.to_checksum_address(addr),
                    deadline,
                    amount_wei,
                    0,
                    0,
                )
                fn = router.functions.exactInputSingle(params)
                tx = {
                    "from": addr,
                    "to": Web3.to_checksum_address(uni_router),
                    "data": fn._encode_transaction_data(),
                    "value": 0,
                    "gas": 250000,
                    "nonce": self.w3.eth.get_transaction_count(addr, "pending"),
                    **cheap_gas,
                }
                result = send_and_confirm(f"UniV3-{fee}", tx)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"UniV3-{fee} sell failed: {str(e)[:100]}")

        return None

    def sell_token_for_eth(
        self,
        token_name: str,
        token_address: str,
        sell_pct: float = 0.3,
        known_balance: Decimal = None,
    ) -> bool:
        """Sell a portion of a token holding to free up ETH for gas and trading.

        Priority: Direct on-chain AMM swaps (cheapest gas) -> Aggregator APIs (last resort)
        """
        if known_balance and known_balance > Decimal("0"):
            token_bal = known_balance
        else:
            token_bal = self.get_token_balance(token_address, "base")
        if token_bal <= Decimal("0"):
            logger.warning(f"No {token_name} balance to sell")
            return False

        sell_amount = token_bal * Decimal(str(sell_pct))
        logger.info(
            f"SELLING {sell_amount:.4f} {token_name} ({sell_pct*100:.0f}% of {token_bal:.4f}) to free up ETH"
        )
        token_decimals = self.get_token_decimals(token_address, "base")
        amount_wei = int(sell_amount * Decimal(10**token_decimals))

        # 1. Try direct on-chain AMM swaps (cheapest gas, no API overhead)
        result = self._direct_cheap_sell(token_address, amount_wei)
        if result:
            return True

        # 2. Last resort: aggregator APIs (higher gas due to complex routing)
        logger.warning(f"All direct swaps failed for {token_name}, trying aggregators")
        for agg_name, agg_func in [
            ("KyberSwap", self._sell_via_kyberswap),
            ("Velora", self._sell_via_velora),
            ("Odos", self._sell_via_odos),
        ]:
            try:
                if agg_func(token_name, token_address, sell_amount):
                    return True
            except Exception as e:
                logger.warning(f"{agg_name} sell failed: {e}")

        logger.error(f"All routes failed to sell {token_name}")
        return False

    def _sell_via_odos(
        self, token_name: str, token_address: str, sell_amount: Decimal
    ) -> bool:
        """Sell via Odos API (higher gas, last resort)."""
        try:
            token_decimals = self.get_token_decimals(token_address, "base")
            amount_wei = str(int(sell_amount * Decimal(10**token_decimals)))

            # Get quote from Odos
            quote_resp = requests.post(
                "https://api.odos.xyz/sor/quote/v2",
                json={
                    "chainId": 8453,
                    "inputTokens": [
                        {"tokenAddress": token_address, "amount": str(amount_wei)}
                    ],
                    "outputTokens": [
                        {
                            "tokenAddress": "0x4200000000000000000000000000000000000006",
                            "proportion": 1,
                        }
                    ],
                    "userAddr": self.evm_account.address,
                    "slippageLimitPercent": 5,
                },
                timeout=15,
            )

            if quote_resp.status_code != 200:
                try:
                    err_body = quote_resp.json()
                    logger.error(
                        f"Odos sell quote failed: {quote_resp.status_code} - {err_body.get('detail', err_body.get('message', quote_resp.text[:200]))}"
                    )
                except:
                    logger.error(
                        f"Odos sell quote failed: {quote_resp.status_code} - {quote_resp.text[:200]}"
                    )
                # Try Velora as fallback (KyberSwap API is unreliable)
                return self._sell_via_velora(token_name, token_address, sell_amount)

            quote = quote_resp.json()

            # Approve Odos router to spend token before assembling
            odos_router = quote.get("transaction", {}).get(
                "to", "0x19960B582773B319a29d7e1f9D7057D0C643396C"
            )
            if not self._erc20_approve_if_needed(
                token_address, odos_router, int(amount_wei)
            ):
                logger.error(f"Failed to approve {token_name} for Odos router")
                return False

            # Wait for approve to mine before swapping
            time.sleep(3)

            # Assemble transaction
            assemble_resp = requests.post(
                "https://api.odos.xyz/sor/assemble",
                json={
                    "userAddr": self.evm_account.address,
                    "pathId": quote.get("pathId"),
                    "simulate": False,
                },
                timeout=15,
            )

            if assemble_resp.status_code != 200:
                logger.error(f"Odos assemble failed: {assemble_resp.status_code}")
                return False

            tx_data = assemble_resp.json().get("transaction", {})
            logger.info(
                f"Odos tx data: to={tx_data.get('to')}, value={tx_data.get('value')}, gas={tx_data.get('gas')}"
            )

            odos_calldata = tx_data.get("data", "")
            if not odos_calldata or len(odos_calldata) <= 2 or odos_calldata == "0x":
                logger.error(
                    "Odos assemble returned empty calldata — tx would revert, aborting"
                )
                return self._sell_via_velora(token_name, token_address, sell_amount)

            tx = {
                "from": self.evm_account.address,
                "to": Web3.to_checksum_address(tx_data.get("to")),
                "data": tx_data.get("data"),
                "value": 0,  # Selling ERC20, no ETH value needed
                "gas": int(tx_data.get("gas", 300000)),
                "maxFeePerGas": max(
                    self.w3.eth.gas_price, 1_000_000
                ),  # live gas, min 0.001 gwei
                "maxPriorityFeePerGas": max(self.w3.eth.gas_price // 10, 100000),
                "nonce": self.w3.eth.get_transaction_count(
                    self.evm_account.address, "latest"
                ),
                "chainId": 8453,
            }

            signed = self.evm_account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 1:
                logger.info(
                    f"SELL CONFIRMED: {token_name} -> WETH | tx: {tx_hash.hex()}"
                )
                return True
            else:
                logger.error(f"Sell failed: {tx_hash.hex()}")
                return False

        except Exception as e:
            logger.error(f"Sell {token_name} error: {e}")
            import traceback

            traceback.print_exc()
            return False

    def should_sell_position(
        self, token: str, position: Dict, new_signal_conf: float = 0
    ) -> bool:
        """Determine if a position should be sold.

        Sells when:
        - Position older than 1 hour (time decay for micro-caps)
        - Position older than 30 min AND a higher-confidence signal appeared
        - Position older than 15 min AND SOL is too low to trade new signals
        """
        entry_time = position.get("timestamp", 0)
        age_seconds = time.time() - entry_time
        chain = position.get("chain", "base")

        # Aggressive rotation for micro-caps: sell after 1 hour
        if age_seconds > 3600:  # 1 hour
            logger.info(
                f"Position {token} is {age_seconds/60:.0f}min old - rotating out (time limit)"
            )
            return True

        # Sell after 30 min if a higher-confidence signal appeared
        if age_seconds > 1800 and new_signal_conf > 0.8:  # 30 min + high conf signal
            logger.info(
                f"Position {token} is {age_seconds/60:.0f}min old - selling for higher conf signal ({new_signal_conf:.2f})"
            )
            return True

        # Sell after 15 min if SOL is too low to trade anything (< 0.002)
        if chain == "solana" and age_seconds > 900:
            sol_bal = self.get_balance("solana")
            if sol_bal < Decimal("0.002"):
                logger.info(
                    f"Position {token} is {age_seconds/60:.0f}min old - selling to free SOL (bal: {sol_bal:.6f})"
                )
                return True

        return False

    # ==================== BRIDGING (CROSS-CHAIN) ====================

    def bridge_quote(
        self, from_chain: str, to_chain: str, token: str, amount: str
    ) -> Dict:
        """Get bridge quote using LiFi."""
        chain_ids = {
            "base": 8453,
            "ethereum": 1,
            "arbitrum": 42161,
            "polygon": 137,
            "bsc": 56,
            "solana": 1151111081099710,
        }

        from_chain_id = chain_ids.get(from_chain, 8453)
        to_chain_id = chain_ids.get(to_chain, 1)

        try:
            resp = requests.get(
                f"{self.LIFI_API}/quote",
                params={
                    "fromChain": from_chain_id,
                    "toChain": to_chain_id,
                    "fromToken": token,
                    "toToken": token,  # Same token on destination
                    "fromAmount": amount,
                    "fromAddress": self.evm_account.address if self.evm_account else "",
                },
                headers={"x-lifi-api-key": self.LIFI_API_KEY},
                timeout=15,
            )

            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Bridge quote error: {e}")
        return {}

    def execute_bridge(
        self, from_chain: str, to_chain: str, token: str, amount: str
    ) -> bool:
        """Execute cross-chain bridge using LiFi."""
        quote = self.bridge_quote(from_chain, to_chain, token, amount)
        if not quote:
            logger.error("Failed to get bridge quote")
            return False

        # LiFi returns transaction data in the quote
        tx_data = quote.get("transactionRequest", {})
        if not tx_data:
            logger.error("No transaction data in bridge quote")
            return False

        logger.info(f"Bridge quote: {amount} {token} from {from_chain} to {to_chain}")

        # Execute the bridge transaction
        try:
            if from_chain == "base" and self.w3 and self.evm_account:
                # EVM chain bridge (Base -> Solana)
                tx = {
                    "from": self.evm_account.address,
                    "to": tx_data.get("to"),
                    "data": tx_data.get("data"),
                    "value": (
                        int(tx_data.get("value", "0"), 16)
                        if isinstance(tx_data.get("value"), str)
                        else int(tx_data.get("value", 0))
                    ),
                    "gas": (
                        int(tx_data.get("gasLimit", "0"), 16)
                        if isinstance(tx_data.get("gasLimit"), str)
                        else int(tx_data.get("gasLimit", 100000))
                    ),
                    "gasPrice": (
                        int(tx_data.get("gasPrice", "0"), 16)
                        if isinstance(tx_data.get("gasPrice"), str)
                        else int(tx_data.get("gasPrice", 0))
                    ),
                    "nonce": self.w3.eth.get_transaction_count(
                        self.evm_account.address
                    ),
                    "chainId": 8453,  # Base chain ID
                }

                # Sign and send transaction
                signed_tx = self.evm_account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                logger.info(f"Bridge transaction sent: {tx_hash.hex()}")

                # Wait for confirmation
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
                if receipt.status == 1:
                    logger.info(f"Bridge successful! TX: {tx_hash.hex()}")
                    return True
                else:
                    logger.error(f"Bridge transaction failed: {tx_hash.hex()}")
                    return False

            elif from_chain == "solana" and self.solana_keypair:
                # Solana bridge (Solana -> Base)
                # LiFi returns Solana transaction as base64
                import base64
                from solders.transaction import VersionedTransaction

                solana_tx_b64 = tx_data.get("transaction", "")
                if not solana_tx_b64:
                    logger.error("No Solana transaction data in bridge quote")
                    return False

                # Decode and sign the transaction
                tx_bytes = base64.b64decode(solana_tx_b64)
                tx = VersionedTransaction.from_bytes(tx_bytes)
                signed_tx = VersionedTransaction(tx.message, [self.solana_keypair])

                # Send the transaction
                if self.solana_adapter:
                    sig = self.solana_adapter.send_tx(signed_tx)
                    if sig:
                        logger.info(f"Bridge successful! TX: {sig}")
                        return True
                    else:
                        logger.error("Bridge transaction failed")
                        return False
                else:
                    logger.error("No Solana adapter available for bridge")
                    return False
            else:
                logger.error(f"Unsupported bridge from {from_chain}")
                return False

        except Exception as e:
            logger.error(f"Bridge execution error: {e}")
            return False

    # ==================== LIQUIDITY POOLING ====================

    def get_pool_info(self, token_a: str, token_b: str, chain: str = "base") -> Dict:
        """Get liquidity pool information."""
        # KyberSwap pool info
        try:
            resp = requests.get(
                f"{self.KYBERSWAP_API}/{chain}/api/v1/pools",
                params={
                    "tokenIn": token_a,
                    "tokenOut": token_b,
                },
                timeout=15,
            )

            if resp.status_code == 200:
                data = resp.json()
                if "data" in data and data["data"]:
                    pool = data["data"][0]
                    return {
                        "address": pool.get("poolAddress"),
                        "liquidity": pool.get("liquidityUsd", 0),
                        "apr": pool.get("apr", 0),
                        "fee": pool.get("fee", 0),
                    }
        except Exception as e:
            logger.error(f"Pool info error: {e}")

        return {}

    def add_liquidity_quote(
        self, token_a: str, token_b: str, amount_a: str, chain: str = "base"
    ) -> Dict:
        """Get quote for adding liquidity."""
        pool_info = self.get_pool_info(token_a, token_b, chain)
        if not pool_info:
            return {}

        # Calculate required amount of token_b based on pool ratio
        # This is simplified - actual implementation would use pool reserves
        return {
            "pool": pool_info.get("address"),
            "liquidity": pool_info.get("liquidity"),
            "apr": pool_info.get("apr"),
            "estimated_lp_tokens": "0",  # Would calculate based on pool
            "price_impact": 0,
        }

    def add_liquidity(
        self,
        token_a: str,
        token_b: str,
        amount_a: str,
        amount_b: str,
        chain: str = "base",
    ) -> bool:
        """Add liquidity to a pool."""
        logger.info(
            f"Adding liquidity: {amount_a} {token_a} + {amount_b} {token_b} on {chain}"
        )

        # Get pool info
        pool_info = self.get_pool_info(token_a, token_b, chain)
        if not pool_info:
            logger.error("Pool not found")
            return False

        # In production, this would:
        # 1. Approve tokens
        # 2. Call router.addLiquidity()
        # 3. Return LP tokens

        logger.info(f"Pool: {pool_info.get('address')}, APR: {pool_info.get('apr')}%")
        return True

    def remove_liquidity(self, lp_token: str, amount: str, chain: str = "base") -> bool:
        """Remove liquidity from a pool."""
        logger.info(f"Removing liquidity: {amount} LP tokens on {chain}")

        # In production, this would:
        # 1. Approve LP token
        # 2. Call router.removeLiquidity()
        # 3. Receive token_a and token_b

        return True

    # ==================== LIMIT ORDERS ====================

    def create_limit_order(
        self,
        token_in: str,
        token_out: str,
        amount: str,
        target_price: str,
        chain: str = "base",
    ) -> Dict:
        """Create a limit order."""
        logger.info(
            f"Creating limit order: {amount} {token_in} -> {token_out} at price {target_price}"
        )

        # Oku supports limit orders
        try:
            resp = requests.post(
                f"{self.OKU_API}/{chain}/limit-order",
                json={
                    "tokenIn": token_in,
                    "tokenOut": token_out,
                    "amountIn": amount,
                    "targetPrice": target_price,
                    "sender": self.evm_account.address if self.evm_account else "",
                },
                timeout=15,
            )

            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Limit order error: {e}")

        return {}

    # ==================== DCA (DOLLAR COST AVERAGING) ====================

    def create_dca_order(
        self, token: str, amount_per_interval: str, intervals: int, chain: str = "base"
    ) -> Dict:
        """Create a DCA (Dollar Cost Averaging) order."""
        logger.info(
            f"Creating DCA order: {amount_per_interval} {token} x {intervals} intervals"
        )

        # Enso supports DCA strategies
        try:
            resp = requests.post(
                f"{self.ENSO_API}/dca",
                json={
                    "token": token,
                    "amountPerInterval": amount_per_interval,
                    "intervals": intervals,
                    "wallet": self.evm_account.address if self.evm_account else "",
                },
                timeout=15,
            )

            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"DCA order error: {e}")

        return {}

    # ==================== MAIN LOOP ====================

    def compare_quotes(
        self, chain: str, token_in: str, token_out: str, amount: str
    ) -> Dict:
        """Compare quotes across all aggregators. On-chain first, APIs as fallback."""
        quotes = {}
        WETH = "0x4200000000000000000000000000000000000006"

        if chain == "solana":
            # Jupiter v6
            jup_quote = self.jupiter_quote(token_in, token_out, int(amount))
            if jup_quote:
                quotes["jupiter"] = {
                    "output": jup_quote.get("outAmount", "0"),
                    "price_impact": jup_quote.get("priceImpactPct", 0),
                }
            else:
                # Fallback to v1 API
                jup_v1 = self.jupiter_v1_quote(token_in, token_out, int(amount))
                if jup_v1:
                    quotes["jupiter_v1"] = {
                        "output": jup_v1.get("outAmount", "0"),
                        "price_impact": jup_v1.get("priceImpactPct", 0),
                    }

            # Raydium
            ray_quote = self.raydium_quote(token_in, token_out, int(amount))
            if ray_quote:
                quotes["raydium"] = {
                    "output": ray_quote.get("outputAmount", "0"),
                    "price_impact": ray_quote.get("priceImpact", 0),
                }

            # OpenOcean (supports Solana)
            oo_quote = self.openocean_quote(chain, token_in, token_out, amount)
            if oo_quote and "data" in oo_quote:
                quotes["openocean"] = {
                    "output": oo_quote["data"].get("outAmount", "0"),
                    "gas": oo_quote["data"].get("estimatedGas", "0"),
                }
        else:
            # === ON-CHAIN QUOTES (free, no API needed) ===

            # Uniswap V3 QuoterV2 (on-chain view function)
            if self.contract_executor:
                t_in = (
                    token_in
                    if token_in != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
                    else WETH
                )
                t_out = (
                    token_out
                    if token_out != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
                    else WETH
                )
                best_uni = 0
                best_fee = 3000
                for fee in [500, 3000, 10000]:
                    out = self.contract_executor.quote_univ3(
                        t_in, t_out, int(amount), fee
                    )
                    if out > best_uni:
                        best_uni = out
                        best_fee = fee
                if best_uni > 0:
                    quotes["uniswap_v3_onchain"] = {
                        "output": str(best_uni),
                        "fee": best_fee,
                        "source": "QuoterV2 (view function)",
                    }

            # === API QUOTES (fallback) ===

            # KyberSwap (also collect build calldata for contract execution)
            ks_quote = self.kyberswap_quote(chain, token_in, token_out, amount)
            if ks_quote and "data" in ks_quote:
                route_summary = ks_quote["data"].get("routeSummary", {})
                amount_out = route_summary.get("amountOut", "0")
                quotes["kyberswap"] = {
                    "output": amount_out,
                    "gas_usd": route_summary.get("gasUsd", "0"),
                }
                # Build calldata for contract execution
                try:
                    import time as _time

                    build_resp = requests.post(
                        f"{self.KYBERSWAP_API}/{chain}/api/v1/route/build",
                        json={
                            "routeSummary": route_summary,
                            "sender": self.evm_account.address,
                            "recipient": self.evm_account.address,
                            "slippageTolerance": 100,
                            "deadline": int(_time.time()) + 1800,
                            "source": "hermes-bot",
                        },
                        headers={"x-client-id": "hermes-bot"},
                        timeout=15,
                    )
                    if build_resp.status_code == 200:
                        bd = build_resp.json()
                        if bd.get("code", -1) == 0 and "data" in bd:
                            tx = bd["data"]
                            quotes["kyberswap"]["_tx"] = {
                                "to": tx.get("routerAddress"),
                                "data": tx.get("data"),
                                "gas": tx.get("gas", 300000),
                                "value": tx.get("transactionValue", "0"),
                            }
                except Exception as e:
                    logger.debug(f"KyberSwap build failed: {e}")

            # OpenOcean
            oo_quote = self.openocean_quote(chain, token_in, token_out, amount)
            if oo_quote and "data" in oo_quote:
                quotes["openocean"] = {
                    "output": oo_quote["data"].get("outAmount", "0"),
                    "gas": oo_quote["data"].get("estimatedGas", "0"),
                }

            # Velora
            vel_quote = self.velora_quote(
                8453 if chain == "base" else 1, token_in, token_out, amount
            )
            if vel_quote and "priceRoute" in vel_quote:
                quotes["velora"] = {
                    "output": vel_quote["priceRoute"].get("destAmount", "0"),
                    "gas": vel_quote["priceRoute"].get("gasCost", "0"),
                }
                # Build Velora tx for contract execution
                try:
                    import time as _time2

                    vel_build = requests.post(
                        f"{self.VELORA_API}/transactions/8453",
                        json={
                            "priceRoute": vel_quote["priceRoute"],
                            "srcToken": token_in,
                            "destToken": token_out,
                            "srcAmount": amount,
                            "destAmount": vel_quote["priceRoute"].get(
                                "destAmount", "0"
                            ),
                            "userAddress": self.evm_account.address,
                            "partner": "hermes-bot",
                        },
                        params={
                            "ignoreChecks": "true",
                        },
                        timeout=15,
                    )
                    if vel_build.status_code == 200:
                        vbd = vel_build.json()
                        quotes["velora"]["_tx"] = {
                            "to": vbd.get("to"),
                            "data": vbd.get("data"),
                            "gas": vbd.get("gas", 300000),
                            "value": vbd.get("value", "0"),
                        }
                except Exception as e:
                    logger.debug(f"Velora build failed: {e}")

            # Odos (also collect assembled tx for contract execution)
            odos_quote = self.odos_quote(chain, token_in, token_out, amount)
            if odos_quote:
                out_amounts = odos_quote.get("outAmounts", ["0"])
                path_id = odos_quote.get("pathId", "")
                quotes["odos"] = {
                    "output": out_amounts[0] if out_amounts else "0",
                    "path_id": path_id,
                    "price_impact": odos_quote.get("priceImpact", 0),
                }
                # Assemble tx for contract execution
                if path_id:
                    try:
                        asm = self.odos_assemble(path_id)
                        if asm and "transaction" in asm:
                            tx = asm["transaction"]
                            quotes["odos"]["_tx"] = {
                                "to": tx.get("to"),
                                "data": tx.get("data"),
                                "gas": tx.get("gas", 300000),
                                "value": tx.get("value", "0"),
                            }
                    except Exception as e:
                        logger.debug(f"Odos assemble failed: {e}")

            # CoW Protocol (Base only, WETH pairs)
            if chain == "base":
                cow_in = (
                    token_in
                    if token_in != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
                    else WETH
                )
                cow_quote = self.cow_quote(cow_in, token_out, amount)
                if cow_quote and "quote" in cow_quote:
                    quotes["cow"] = {
                        "output": cow_quote["quote"].get("buyAmount", "0"),
                        "fee_amount": cow_quote["quote"].get("feeAmount", "0"),
                    }

            # LiFi (multi-chain)
            lifi_quote = self.lifi_quote(
                chain,
                chain,
                token_in,
                token_out,
                amount,
                self.evm_account.address if self.evm_account else "",
            )
            if lifi_quote and "estimate" in lifi_quote:
                estimate = lifi_quote["estimate"]
                if isinstance(estimate, dict):
                    quotes["lifi"] = {
                        "output": estimate.get("toAmount", "0"),
                        "gas_cost_usd": (
                            estimate.get("gasCosts", [{}])[0].get("amountUSD", "0")
                            if estimate.get("gasCosts")
                            else "0"
                        ),
                    }

            # Enso (rate-limited, skip if recently called)
            if not self._enso_rate_limited:
                enso_quote = self.enso_quote(chain, token_in, token_out, amount)
                if enso_quote:
                    quotes["enso"] = {
                        "output": enso_quote.get("amountOut", "0"),
                        "gas": enso_quote.get("gas", "0"),
                    }
                else:
                    self._enso_rate_limited = True

        return quotes

    def refuel_base_gas(self, min_eth: float = 0.00005) -> bool:
        """Swap USDC -> ETH on Base when ETH is critically low. Uses KyberSwap API.
        Mirrors the working _sell_via_kyberswap pattern."""
        if not self.w3 or not self.evm_account:
            return False
        try:
            usdc_addr = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
            weth = "0x4200000000000000000000000000000000000006"

            # Check current USDC balance
            usdc_bal = self.get_token_balance(usdc_addr, "base")
            if usdc_bal < Decimal("0.05"):
                logger.warning(f"[Refuel] USDC too low ({usdc_bal:.4f}) to refuel gas")
                return False

            # Check if we actually need refueling
            eth_bal = Decimal(
                str(self.w3.eth.get_balance(self.evm_account.address) / 1e18)
            )
            if eth_bal >= Decimal(str(min_eth)):
                logger.debug(
                    f"[Refuel] ETH sufficient ({eth_bal:.8f}), skipping refuel"
                )
                return True

            # Swap ~$0.10 USDC -> ETH (100000 = 0.10 USDC in 6 decimals)
            swap_amount = min(int(usdc_bal * 1_000_000), 100000)  # max 0.10 USDC
            if swap_amount < 50000:  # less than $0.05
                logger.warning(f"[Refuel] Swap amount too small: {swap_amount}")
                return False
            amount_wei = str(swap_amount)

            # Get KyberSwap quote via GET (V1 API)
            quote_url = "https://aggregator-api.kyberswap.com/base/api/v1/routes"
            quote_resp = requests.get(
                quote_url,
                params={
                    "tokenIn": usdc_addr,
                    "tokenOut": weth,
                    "amountIn": amount_wei,
                },
                headers={"x-client-id": "hermes-bot"},
                timeout=15,
            )
            if quote_resp.status_code != 200:
                logger.error(f"[Refuel] Quote failed: {quote_resp.status_code}")
                return False

            quote_json = quote_resp.json()
            if quote_json.get("code", -1) != 0:
                logger.error(
                    f"[Refuel] Quote error: {quote_json.get('message', 'Unknown')}"
                )
                return False

            route_data = quote_json.get("data", {})
            route_summary = route_data.get("routeSummary", {})
            amount_out = int(route_summary.get("amountOut", 0))
            if amount_out == 0:
                logger.error("[Refuel] Zero output from quote")
                return False

            eth_out = amount_out / 1e18
            logger.info(
                f"[Refuel] Quote: {swap_amount/1e6:.4f} USDC -> {eth_out:.8f} ETH (via WETH)"
            )

            # Build swap transaction FIRST (V1 API: router address only in build response)
            build_resp = requests.post(
                "https://aggregator-api.kyberswap.com/base/api/v1/route/build",
                json={
                    "routeSummary": route_summary,
                    "sender": self.evm_account.address,
                    "recipient": self.evm_account.address,
                    "slippageTolerance": 500,
                    "deadline": int(time.time()) + 1800,
                    "source": "hermes-bot",
                },
                headers={"x-client-id": "hermes-bot"},
                timeout=15,
            )
            if build_resp.status_code != 200:
                logger.error(f"[Refuel] Build failed: {build_resp.status_code}")
                return False

            build_json = build_resp.json()
            if build_json.get("code", -1) != 0:
                logger.error(
                    f"[Refuel] Build error: {build_json.get('message', 'Unknown')}"
                )
                return False

            tx_data = build_json.get("data", {})
            router_address = tx_data.get("routerAddress", "")

            # Approve USDC spending (now that we have router address)
            if not self._erc20_approve_if_needed(
                usdc_addr, router_address, swap_amount
            ):
                logger.error("[Refuel] Failed to approve USDC for KyberSwap")
                return False

            # Construct and send swap tx (matching _sell_via_kyberswap pattern)
            swap_tx = {
                "from": self.evm_account.address,
                "to": Web3.to_checksum_address(
                    tx_data.get("routerAddress", router_address)
                ),
                "data": tx_data.get("data"),
                "value": 0,  # ERC20 -> WETH: no native ETH value
                "gas": int(tx_data.get("gas", 300000)),
                "maxFeePerGas": self.w3.eth.gas_price,
                "maxPriorityFeePerGas": self.w3.eth.max_priority_fee,
                "nonce": self.w3.eth.get_transaction_count(
                    self.evm_account.address, "pending"
                ),
                "chainId": 8453,
            }

            signed = self.evm_account.sign_transaction(swap_tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            logger.info(f"[Refuel] Swap sent: {tx_hash.hex()}")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 1:
                new_eth = Decimal(
                    str(self.w3.eth.get_balance(self.evm_account.address) / 1e18)
                )
                logger.info(f"[Refuel] SUCCESS! New ETH balance: {new_eth:.8f} ETH")
                # Unwrap WETH to native ETH if we got WETH
                weth_bal = self.get_token_balance(weth, "base")
                if weth_bal > Decimal("0.00001"):
                    logger.info(f"[Refuel] Unwrapping {weth_bal:.8f} WETH to ETH")
                    self._unwrap_weth(weth_bal)
                return True
            else:
                logger.error(f"[Refuel] Swap tx failed: {tx_hash.hex()}")
                return False

        except Exception as e:
            logger.error(f"[Refuel] Error: {e}")
            import traceback

            traceback.print_exc()
            return False

    def execute_base_trade(
        self, token_symbol: str, token_addr: str, eth_amount: float
    ) -> bool:
        """Execute a trade on Base. Tries direct contract first, falls back to KyberSwap API."""
        amount_wei = int(eth_amount * 1e18)

        # Collect API routes for aggregator protocols
        api_routes = {}
        try:
            # Use NATIVE_ETH for native swaps (API supports it)
            t_in = NATIVE_ETH
            quotes = self.compare_quotes("base", t_in, token_addr, str(amount_wei))
            for proto in ["kyberswap", "odos", "velora"]:
                if proto in quotes and "_tx" in quotes[proto]:
                    api_routes[proto] = quotes[proto]["_tx"]
                    logger.info(
                        f"  Collected {proto} route: {quotes[proto].get('output', '?')} out"
                    )
        except Exception as e:
            logger.debug(f"Route collection failed: {e}")

        # === PRIMARY: Direct contract execution ===
        if self.contract_executor:
            try:
                logger.info(
                    f"[Contract] Attempting direct on-chain swap: {eth_amount:.6f} ETH -> {token_symbol}"
                )
                tx_hash = self.contract_executor.smart_swap(
                    token_in=NATIVE_ETH,
                    token_out=token_addr,
                    amount_in=amount_wei,
                    slippage_bps=100,
                    api_routes=api_routes,
                )
                if tx_hash:
                    logger.info(f"[Contract] Trade confirmed: {tx_hash}")
                    return True
                else:
                    logger.warning(
                        "[Contract] Direct swap failed, falling back to API..."
                    )
            except Exception as e:
                logger.warning(f"[Contract] Error: {e}, falling back to API...")

        # === FALLBACK: KyberSwap API ===
        return self._execute_base_trade_api(token_symbol, token_addr, eth_amount)

    def _execute_base_trade_api(
        self, token_symbol: str, token_addr: str, eth_amount: float
    ) -> bool:
        """Execute a trade on Base using KyberSwap API (fallback)."""
        try:
            import time

            # Use native ETH address for KyberSwap
            ETH_NATIVE = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
            amount_wei = str(int(eth_amount * 1e18))

            # Get quote with native ETH
            quote = self.kyberswap_quote("base", ETH_NATIVE, token_addr, amount_wei)
            if not quote or "data" not in quote:
                logger.error(f"Failed to get quote for {token_symbol}")
                return False

            route = quote["data"].get("routeSummary", {})
            amount_out = int(route.get("amountOut", 0))

            if amount_out == 0:
                logger.error(f"Zero output amount for {token_symbol}")
                return False

            logger.info(f"Quote: {eth_amount:.6f} ETH -> {amount_out} {token_symbol}")

            # Build transaction with proper deadline
            deadline = int(time.time()) + 1800  # 30 minutes from now

            build_body = {
                "routeSummary": route,
                "sender": self.evm_account.address,
                "recipient": self.evm_account.address,
                "slippageTolerance": 100,  # 1%
                "deadline": deadline,
                "source": "hermes-bot",
            }

            build_resp = requests.post(
                "https://aggregator-api.kyberswap.com/base/api/v1/route/build",
                json=build_body,
                headers={"x-client-id": "hermes-bot"},
                timeout=15,
            )

            if build_resp.status_code != 200:
                logger.error(f"Build failed: {build_resp.text[:200]}")
                return False

            build_data = build_resp.json()

            # Validate response
            if build_data.get("code", 0) != 0:
                logger.error(f"Build error: {build_data.get('message', 'Unknown')}")
                return False

            if "data" not in build_data:
                logger.error("No data in build response")
                return False

            tx_data = build_data["data"]

            # Extract fields
            router_address = tx_data.get("routerAddress")
            transaction_value = tx_data.get("transactionValue", "0")
            calldata = tx_data.get("data")

            # Validate
            if not router_address or len(router_address) != 42:
                logger.error(f"Invalid router address: {router_address}")
                return False

            if not calldata or not calldata.startswith("0x"):
                logger.error("Invalid calldata")
                return False

            logger.info(f"Router: {router_address}, Value: {transaction_value} wei")

            # Send transaction
            if self.w3:
                tx = {
                    "from": self.evm_account.address,
                    "to": router_address,
                    "data": calldata,
                    "value": (
                        int(transaction_value, 16)
                        if isinstance(transaction_value, str)
                        and transaction_value.startswith("0x")
                        else int(transaction_value)
                    ),
                    "gas": int(tx_data.get("gas", 300000)),
                    "maxFeePerGas": self.w3.eth.gas_price,
                    "maxPriorityFeePerGas": self.w3.eth.max_priority_fee,
                    "nonce": self.w3.eth.get_transaction_count(
                        self.evm_account.address, "pending"
                    ),
                    "chainId": 8453,
                }

                signed = self.evm_account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)

                logger.info(f"Trade sent: {tx_hash.hex()}")

                # Wait for receipt
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                if receipt.status == 1:
                    logger.info(f"Trade confirmed: {tx_hash.hex()}")
                    return True
                else:
                    logger.error(f"Trade failed: {tx_hash.hex()}")
                    return False

        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            import traceback

            traceback.print_exc()

        return False

    def execute_solana_trade(
        self, token_symbol: str, token_mint: str, sol_amount: float
    ) -> bool:
        """Execute a trade on Solana. For pump.fun tokens, uses PumpFun CLI directly."""

        SOL_MINT = "So11111111111111111111111111111111111111112"
        amount_base = int(sol_amount * 1e9)

        # === OPTIMIZATION: For pump.fun tokens, use PumpFun CLI when SOL buffer is sufficient ===
        if "pump" in token_mint.lower():
            current_sol = self.get_balance("solana")
            # PumpFun buys often need extra SOL headroom for rent/ATA creation.
            if current_sol >= Decimal("0.0045"):
                logger.info(
                    "[Solana] Pump.fun token detected, using PumpFun CLI directly"
                )
                try:
                    if self.execute_pumpfun_trade(token_mint, sol_amount):
                        return True
                except Exception as e:
                    logger.error(f"[PumpFun] Trade failed: {e}")
                # If PumpFun fails, try Jupiter CLI as final fallback
                return self._execute_solana_trade_cli(
                    token_symbol, token_mint, sol_amount
                )
            else:
                logger.info(
                    f"[Solana] Pump.fun token but SOL={current_sol:.6f} below PumpFun safety buffer; trying Jupiter/Raydium/Meteora"
                )

        # === PRIMARY: Solana adapter with multiple DEX fallbacks for non-pump tokens ===
        if self.solana_adapter:
            # Route 1: Jupiter API (best for listed tokens)
            try:
                logger.info(
                    f"[Solana/Jupiter] Swapping {sol_amount:.6f} SOL -> {token_symbol}"
                )
                sig = self.solana_adapter.swap(
                    input_mint=SOL_MINT,
                    output_mint=token_mint,
                    amount=amount_base,
                    slippage_bps=100,
                )
                if sig:
                    logger.info(f"[Solana/Jupiter] Trade confirmed: {sig}")
                    return True
                else:
                    logger.warning("[Solana/Jupiter] Swap returned None")
            except Exception as e:
                logger.warning(f"[Solana/Jupiter] Error: {e}")

            # Route 2: Raydium CPMM (works for graduated tokens)
            try:
                logger.info(
                    f"[Solana/Raydium] Quoting {sol_amount:.6f} SOL -> {token_symbol}"
                )
                quote = self.solana_adapter.raydium_cpmm_quote(
                    SOL_MINT,
                    token_mint,
                    amount_base,
                    slippage_bps=300,  # 3% slippage for illiquid
                )
                if quote:
                    tx = self.solana_adapter.raydium_build_tx(quote)
                    if tx:
                        sim_ok, sim_err = self.solana_adapter.simulate_tx(tx)
                        if sim_ok:
                            sig = self.solana_adapter.send_tx(tx)
                            if sig:
                                self.solana_adapter.confirm_tx(sig)
                                logger.info(f"[Solana/Raydium] Trade confirmed: {sig}")
                                return True
                        else:
                            logger.warning(f"[Solana/Raydium] Sim failed: {sim_err}")
            except Exception as e:
                logger.warning(f"[Solana/Raydium] Error: {e}")

            # Route 3: Meteora DLMM
            try:
                logger.info(
                    f"[Solana/Meteora] Quoting {sol_amount:.6f} SOL -> {token_symbol}"
                )
                quote = self.solana_adapter.meteora_quote(
                    SOL_MINT, token_mint, amount_base, slippage_bps=300
                )
                if quote:
                    tx = self.solana_adapter.meteora_build_tx(quote)
                    if tx:
                        sig = self.solana_adapter.send_tx(tx)
                        if sig:
                            self.solana_adapter.confirm_tx(sig)
                            logger.info(f"[Solana/Meteora] Trade confirmed: {sig}")
                            return True
            except Exception as e:
                logger.warning(f"[Solana/Meteora] Error: {e}")

            logger.warning("[Solana] All adapter routes failed, falling back to CLI...")

        # === FALLBACK: Jupiter CLI ===
        return self._execute_solana_trade_cli(token_symbol, token_mint, sol_amount)

    def execute_pumpfun_trade(self, token_mint: str, sol_amount: float) -> bool:
        """Execute a pump.fun / PumpSwap trade using pumpfun-cli.

        This handles bonding curve vs PumpSwap AMM automatically.
        Requires pumpfun-cli and a configured wallet (PUMPFUN_PASSWORD, keyfile).
        Uses RPC fallback chain if primary is down.
        """
        try:
            import subprocess

            amount_str = str(sol_amount)

            # Build RPC fallback chain (primary first)
            primary_rpc = os.environ.get(
                "PUMPFUN_RPC",
                os.environ.get(
                    "SOLANA_RPC_URL",
                    "https://mainnet.helius-rpc.com/?api-key=bb6ff3e9-e38d-4362-9e7a-669a00d497a8",
                ),
            )
            fallback_raw = os.environ.get(
                "PUMPFUN_RPC_FALLBACKS",
                "https://api.mainnet-beta.solana.com,https://rpc.ankr.com/solana",
            )
            rpc_chain = [primary_rpc] + [
                r.strip() for r in fallback_raw.split(",") if r.strip()
            ]

            env = {
                **os.environ,
                "PUMPFUN_PASSWORD": os.environ.get("PUMPFUN_PASSWORD", "hermes"),
                # Ensure pumpfun executable is found even in daemon PATH
                "PATH": os.environ.get("PATH", "") + ":/home/terexitarius/.local/bin",
                # Ensure pumpfun-cli can find its IDL
                "PYTHONPATH": os.environ.get("PYTHONPATH", "")
                + ":/home/terexitarius/.local/share/uv/tools/pumpfun-cli/lib/python3.12/site-packages",
            }

            for rpc in rpc_chain:
                cmd = [
                    "pumpfun",
                    "--rpc",
                    rpc,
                    "buy",
                    token_mint,
                    amount_str,
                    "--slippage",
                    "15",
                    "--confirm",
                    "--json",
                ]

                logger.info(
                    f"[PumpFun] Executing via RPC {rpc}: {amount_str} SOL -> {token_mint}"
                )

                # Dry-run first for safety
                dry_cmd = cmd + ["--dry-run"]
                dry = subprocess.run(
                    dry_cmd,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                )
                if dry.returncode != 0:
                    logger.error(
                        f"[PumpFun] Dry-run failed on {rpc}: {dry.stderr[:200]}"
                    )
                    continue

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                )

                if result.returncode == 0:
                    logger.info(f"[PumpFun] Buy successful: {result.stdout[:200]}")
                    return True
                else:
                    logger.error(
                        f"[PumpFun] Buy failed on {rpc}: {result.stderr[:200]}"
                    )

        except Exception as e:
            logger.error(f"[PumpFun] Error: {e}")

        return False

    def _execute_solana_trade_cli(
        self, token_symbol: str, token_mint: str, sol_amount: float
    ) -> bool:
        """Execute a trade on Solana using Jupiter CLI (fallback)."""
        try:
            import subprocess

            amount_str = str(sol_amount)

            # Use Jupiter CLI for swap
            cmd = [
                "/home/terexitarius/.hermes/node/bin/jup",
                "spot",
                "swap",
                "--from",
                "SOL",
                "--to",
                token_mint,
                "--amount",
                amount_str,
                "--slippage",
                "1",
            ]

            logger.info(f"Executing Jupiter swap: {amount_str} SOL -> {token_symbol}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env={
                    **os.environ,
                    "PATH": os.environ.get("PATH", "")
                    + ":/home/terexitarius/.hermes/node/bin",
                },
            )

            if result.returncode == 0:
                logger.info(f"Jupiter swap successful: {result.stdout[:200]}")
                return True
            else:
                logger.error(f"Jupiter swap failed: {result.stderr[:200]}")

        except Exception as e:
            logger.error(f"Solana trade error: {e}")

        return False

    def sell_solana_token(
        self, token_symbol: str, token_mint: str, sell_pct: float = 1.0
    ) -> bool:
        """Sell a Solana token back to SOL using multi-DEX routing.

        Tries: Jupiter -> Raydium -> Meteora -> Orca -> PumpSwap
        """
        SOL_MINT = "So11111111111111111111111111111111111111112"

        if not self.solana_keypair:
            logger.error("[Solana Sell] No Solana wallet configured")
            return False

        try:

            wallet = str(self.solana_keypair.pubkey())

            # Get token balance
            if self.solana_adapter:
                balance = self.solana_adapter.get_token_balance(token_mint, wallet)
            else:
                balance = 0

            if balance <= 0:
                # Token accounts can take a moment to appear after fresh buys
                for _ in range(5):
                    time.sleep(2)
                    if self.solana_adapter:
                        balance = self.solana_adapter.get_token_balance(
                            token_mint, wallet
                        )
                    if balance > 0:
                        break

            if balance <= 0:
                logger.warning(f"[Solana Sell] No {token_symbol} balance to sell")
                return False

            sell_amount = int(balance * sell_pct)
            logger.info(
                f"[Solana Sell] Selling {sell_pct*100:.0f}% of {token_symbol}: "
                f"{sell_amount} units"
            )

            # === Route 1: Jupiter (aggregator, best price) ===
            try:
                if self.solana_adapter:
                    sig = self.solana_adapter.swap(
                        input_mint=token_mint,
                        output_mint=SOL_MINT,
                        amount=sell_amount,
                        slippage_bps=200,  # 2% slippage for sells
                    )
                    if sig:
                        logger.info(f"[Solana Sell] Jupiter sell confirmed: {sig}")
                        return True
            except Exception as e:
                logger.warning(f"[Solana Sell] Jupiter failed: {e}")

            # === Route 2: Jupiter CLI ===
            try:
                import subprocess

                decimals = SOLANA_TOKENS.get(token_symbol.upper(), {}).get(
                    "decimals", 9
                )
                token_amount = sell_amount / (10**decimals)  # Convert to human-readable
                cmd = [
                    "/home/terexitarius/.hermes/node/bin/jup",
                    "spot",
                    "swap",
                    "--from",
                    token_mint,
                    "--to",
                    "SOL",
                    "--amount",
                    str(token_amount),
                    "--slippage",
                    "2",
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env={
                        **os.environ,
                        "PATH": os.environ.get("PATH", "")
                        + ":/home/terexitarius/.hermes/node/bin",
                    },
                )
                if result.returncode == 0:
                    logger.info(f"[Solana Sell] Jupiter CLI sell successful")
                    return True
            except Exception as e:
                logger.warning(f"[Solana Sell] Jupiter CLI failed: {e}")

            # === Route 3: Raydium direct ===
            try:
                if self.solana_adapter:
                    ray_quote = self.solana_adapter.raydium_cpmm_quote(
                        token_mint, SOL_MINT, sell_amount, slippage_bps=200
                    )
                    if ray_quote:
                        tx = self.solana_adapter.raydium_build_tx(ray_quote)
                        if tx:
                            sig = self.solana_adapter.send_tx(tx)
                            if sig:
                                logger.info(
                                    f"[Solana Sell] Raydium sell confirmed: {sig}"
                                )
                                return True
            except Exception as e:
                logger.warning(f"[Solana Sell] Raydium failed: {e}")

            # === Route 4: Meteora DLMM ===
            try:
                if self.solana_adapter:
                    met_quote = self.solana_adapter.meteora_quote(
                        token_mint, SOL_MINT, sell_amount, slippage_bps=200
                    )
                    if met_quote and met_quote.get("pool"):
                        tx_b64 = self.solana_adapter.meteora_build_tx(
                            met_quote, wallet, sell_amount, slippage_bps=200
                        )
                        if tx_b64:
                            import base64

                            from solders.transaction import VersionedTransaction

                            tx_bytes = base64.b64decode(tx_b64)
                            tx = VersionedTransaction.from_bytes(tx_bytes)
                            signed_tx = VersionedTransaction(
                                tx.message, [self.solana_keypair]
                            )
                            sig = self.solana_adapter.send_tx(signed_tx)
                            if sig:
                                logger.info(
                                    f"[Solana Sell] Meteora sell confirmed: {sig}"
                                )
                                return True
            except Exception as e:
                logger.warning(f"[Solana Sell] Meteora failed: {e}")

            # === Route 5: Orca Whirlpool ===
            try:
                if self.solana_adapter:
                    orc_quote = self.solana_adapter.orca_quote(
                        token_mint, SOL_MINT, sell_amount, slippage_bps=200
                    )
                    if orc_quote and orc_quote.get("pool"):
                        tx_b64 = self.solana_adapter.orca_build_tx(
                            orc_quote, wallet, sell_amount, slippage_bps=200
                        )
                        if tx_b64:
                            import base64

                            from solders.transaction import VersionedTransaction

                            tx_bytes = base64.b64decode(tx_b64)
                            tx = VersionedTransaction.from_bytes(tx_bytes)
                            signed_tx = VersionedTransaction(
                                tx.message, [self.solana_keypair]
                            )
                            sig = self.solana_adapter.send_tx(signed_tx)
                            if sig:
                                logger.info(f"[Solana Sell] Orca sell confirmed: {sig}")
                                return True
            except Exception as e:
                logger.warning(f"[Solana Sell] Orca failed: {e}")

            logger.error(f"[Solana Sell] All routes failed for {token_symbol}")
            return False

        except Exception as e:
            logger.error(f"[Solana Sell] Error: {e}")
            return False

    def execute_odos_trade(
        self, token_symbol: str, token_addr: str, eth_amount: float
    ) -> bool:
        """Execute a trade on Base using Odos."""
        try:
            ETH_NATIVE = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
            amount_wei = str(int(eth_amount * 1e18))

            # Get quote
            quote = self.odos_quote("base", ETH_NATIVE, token_addr, amount_wei)
            if not quote:
                logger.error(f"Odos quote failed for {token_symbol}")
                return False

            path_id = quote.get("pathId")
            out_amounts = quote.get("outAmounts", ["0"])
            if not path_id or not out_amounts:
                logger.error("Odos: no path ID or output")
                return False

            logger.info(
                f"Odos quote: {eth_amount:.6f} ETH -> {out_amounts[0]} {token_symbol}"
            )

            # Assemble transaction
            assembled = self.odos_assemble(path_id)
            if not assembled or "transaction" not in assembled:
                logger.error("Odos: failed to assemble transaction")
                return False

            tx = assembled["transaction"]

            if self.w3:
                # Build and send transaction
                tx_data = {
                    "from": self.evm_account.address,
                    "to": tx.get("to"),
                    "data": tx.get("data"),
                    "value": (
                        int(tx.get("value", "0"), 16)
                        if isinstance(tx.get("value"), str)
                        and tx.get("value", "").startswith("0x")
                        else int(tx.get("value", "0"))
                    ),
                    "gas": int(tx.get("gas", 300000)),
                    "maxFeePerGas": self.w3.eth.gas_price,
                    "maxPriorityFeePerGas": self.w3.eth.max_priority_fee,
                    "nonce": self.w3.eth.get_transaction_count(
                        self.evm_account.address, "pending"
                    ),
                    "chainId": 8453,
                }

                signed = self.evm_account.sign_transaction(tx_data)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)

                logger.info(f"Odos trade sent: {tx_hash.hex()}")

                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                if receipt.status == 1:
                    logger.info(f"Odos trade confirmed: {tx_hash.hex()}")
                    return True
                else:
                    logger.error(f"Odos trade failed: {tx_hash.hex()}")
                    return False

        except Exception as e:
            logger.error(f"Odos trade error: {e}")
            import traceback

            traceback.print_exc()

        return False

    def run(self):
        """Main trading loop - executes actual trades with all capabilities."""
        logger.info("Starting DEX Aggregator Trader...")

        # Refresh SOL gas reserve from live price each cycle
        self._refresh_sol_gas_reserve()

        # Track positions and strategies
        # Load existing positions from trade history (survives restarts)
        active_positions = {}
        for key, buy_data in self.trade_history.get("buys", {}).items():
            token = buy_data.get("token", "")
            chain = buy_data.get("chain", "")
            if token:
                active_positions[token] = {
                    "chain": chain,
                    "address": buy_data.get("address", ""),
                    "amount": buy_data.get("amount", 0),
                    "entry_price": 0,
                    "timestamp": buy_data.get("timestamp", time.time()),
                }
        if active_positions:
            logger.info(
                f"Loaded {len(active_positions)} existing positions: {list(active_positions.keys())}"
            )
        limit_orders = {}
        dca_schedules = {}

        while True:
            try:
                base_bal = self.get_balance("base")
                sol_bal = self.get_balance("solana")
                logger.info(
                    f"Balances - Base: {base_bal:.6f} ETH, Solana: {sol_bal:.6f} SOL"
                )

                # ==================== REFUEL BASE GAS FROM USDC ====================
                # If ETH critically low, try swapping USDC -> ETH via KyberSwap
                if base_bal < self.BASE_GAS_RESERVE:
                    logger.info(
                        f"Base ETH low ({base_bal:.8f}), attempting USDC refuel..."
                    )
                    if self.refuel_base_gas():
                        base_bal = self.get_balance("base")
                        logger.info(f"Post-refuel Base balance: {base_bal:.8f} ETH")

                # ==================== CHECK ALL HOLDINGS ====================
                holdings = self.get_all_holdings()
                if holdings:
                    holding_str = ", ".join(
                        f"{k}: {v['balance']:.2f}" for k, v in holdings.items()
                    )
                    logger.info(f"Token holdings: {holding_str}")

                # ==================== PRUNE STALE POSITIONS ====================
                # Prevent repeated sell loops for positions that no longer exist on-chain.
                removed_stale = self._prune_stale_active_positions(
                    active_positions, holdings
                )
                if removed_stale > 0:
                    logger.info(
                        f"[Position Cleanup] Removed {removed_stale} stale positions before rotation"
                    )

                # ==================== FREE UP ETH FROM TOKEN HOLDINGS ====================
                # If ETH is too low to trade but we have token holdings, sell some to get ETH
                # Trigger sell if ETH < 0.0005 (~$1) — need gas buffer for multiple trades
                if base_bal < Decimal("0.0005") and holdings:
                    for tok_name, tok_info in holdings.items():
                        if tok_name == "WETH":
                            # Unwrap WETH to ETH
                            if tok_info["balance"] > Decimal("0.00001"):
                                logger.info(
                                    f"Unwrapping {tok_info['balance']:.6f} WETH to ETH"
                                )
                                self._unwrap_weth(tok_info["balance"])
                                time.sleep(2)
                                base_bal = self.get_balance("base")
                            continue
                        if tok_name in active_positions:
                            continue  # Don't sell active positions
                        logger.info(
                            f"ETH low ({base_bal:.6f}), selling some {tok_name} to free up capital"
                        )
                        sold = self.sell_token_for_eth(
                            tok_name,
                            tok_info["address"],
                            sell_pct=0.5,
                            known_balance=tok_info["balance"],
                        )
                        if sold:
                            time.sleep(3)  # Wait for state to update
                            base_bal = self.get_balance("base")
                            logger.info(f"ETH after sell: {base_bal:.6f}")
                            break  # One sell per cycle

                # ==================== ROTATE OLD POSITIONS ====================
                # First, find the best new BUY signal (for sell-to-upgrade logic)
                best_new_conf = 0
                for sig in signals if "signals" in dir() else []:
                    if sig.get("action") == "BUY":
                        best_new_conf = max(best_new_conf, sig.get("confidence", 0))

                for token, position in list(active_positions.items()):
                    chain = position.get("chain", "base")
                    if self.should_sell_position(
                        token, position, new_signal_conf=best_new_conf
                    ):
                        if chain == "base":
                            token_addr = self.get_token_address(token, "base")
                            # Check actual token balance before attempting sell
                            if token_addr:
                                token_bal = self.get_token_balance(token_addr, "base")
                                if token_bal <= Decimal("0"):
                                    logger.info(
                                        f"[Position Cleanup] Dropping stale {token} on base "
                                        f"(no on-chain balance during rotation)"
                                    )
                                    self._remove_stale_buy(
                                        token, chain, reason="no balance at rotation"
                                    )
                                    del active_positions[token]
                                    continue
                            else:
                                # No address found - can't sell
                                logger.info(
                                    f"[Position Cleanup] Dropping {token} on base "
                                    f"(no token address found)"
                                )
                                self._remove_stale_buy(
                                    token, chain, reason="no address"
                                )
                                del active_positions[token]
                                continue
                            if base_bal > self.BASE_GAS_RESERVE:
                                logger.info(
                                    f"Rotating: selling {token} on Base to chase faster movers"
                                )
                                sold = self.sell_token_for_eth(
                                    token,
                                    token_addr,
                                    sell_pct=1.0,
                                    known_balance=token_bal if token_addr else None,
                                )
                                if sold:
                                    self.record_sell(token, chain)
                                    del active_positions[token]
                                    time.sleep(3)
                                    base_bal = self.get_balance("base")
                                else:
                                    # If sell failed due to no balance, clean up
                                    check_bal = self.get_token_balance(
                                        token_addr, "base"
                                    )
                                    if check_bal <= Decimal("0"):
                                        logger.info(
                                            f"[Position Cleanup] Dropping stale {token} on base "
                                            f"(sell failed - no on-chain balance)"
                                        )
                                        self._remove_stale_buy(
                                            token,
                                            chain,
                                            reason="sell failed, no balance",
                                        )
                                        del active_positions[token]
                            elif token_addr and base_bal <= self.BASE_GAS_RESERVE:
                                logger.debug(
                                    f"Skipping rotation sell for {token}: "
                                    f"insufficient ETH for gas ({base_bal:.8f})"
                                )
                        elif chain == "solana":
                            token_addr = position.get("address", "")
                            sol_bal = self.get_balance("solana")
                            # Check actual token balance before attempting sell
                            if token_addr and self.solana_adapter:
                                wallet = str(self.solana_keypair.pubkey())
                                on_chain_bal = self.solana_adapter.get_token_balance(
                                    token_addr, wallet
                                )
                                if on_chain_bal <= 0:
                                    logger.info(
                                        f"[Position Cleanup] Dropping stale {token} on solana "
                                        f"(no on-chain balance during rotation)"
                                    )
                                    self._remove_stale_buy(
                                        token, chain, reason="no balance at rotation"
                                    )
                                    del active_positions[token]
                                    continue
                            if token_addr and sol_bal > Decimal("0.001"):
                                logger.info(
                                    f"Rotating: selling {token} on Solana to free up SOL"
                                )
                                sold = self.sell_solana_token(
                                    token, token_addr, sell_pct=1.0
                                )
                                if sold:
                                    self.record_sell(token, chain)
                                    del active_positions[token]
                                    time.sleep(3)
                                else:
                                    logger.warning(f"Failed to sell {token} on Solana")
                                    # Re-check: if no balance, clean up stale position
                                    if self.solana_adapter:
                                        wallet = str(self.solana_keypair.pubkey())
                                        recheck = self.solana_adapter.get_token_balance(
                                            token_addr, wallet
                                        )
                                        if recheck <= 0:
                                            logger.info(
                                                f"[Position Cleanup] Dropping stale {token} on solana "
                                                f"(sell failed - no on-chain balance)"
                                            )
                                            self._remove_stale_buy(
                                                token,
                                                chain,
                                                reason="sell failed, no balance",
                                            )
                                            del active_positions[token]
                            elif sol_bal <= self.SOLANA_GAS_RESERVE:
                                logger.debug(
                                    f"Skipping rotation sell for {token}: "
                                    f"insufficient SOL ({sol_bal:.6f})"
                                )

                # ==================== SIGNAL-BASED TRADING ====================
                try:
                    from signal_providers import (
                        aggregate_signals,
                        ScreenerPipelineProvider,
                    )

                    signals = aggregate_signals()

                    # Also add screener tokens directly (bypass merge which loses details)
                    screener_sigs = ScreenerPipelineProvider().fetch()
                    for ss in screener_sigs:
                        if (
                            ss["action"] == "BUY"
                            and ss["confidence"] >= 0.5
                            and ss.get("token_address")
                        ):
                            # Check not already in signals
                            if not any(s.get("token") == ss["token"] for s in signals):
                                signals.append(ss)

                    logger.info(f"Signals: {len(signals)}")

                    for signal in signals:
                        token = signal.get("token", "?")
                        action = signal.get("action", "?")
                        conf = signal.get("confidence", 0)
                        chain = signal.get("chain", "base")
                        src = signal.get("source", "?")
                        logger.info(
                            f"  Signal: {token} {action} conf={conf:.2f} chain={chain} src={src}"
                        )

                        # Only trade on high-confidence BUY signals
                        # Screener tokens already filtered, use lower threshold for them
                        min_conf = 0.5 if signal.get("source") == "Screener" else 0.7
                        if action == "BUY" and conf >= min_conf:
                            # Use token_address from signal if available (Dexscreener, SmartMoney)
                            token_addr = signal.get(
                                "token_address"
                            ) or self.get_token_address(token, chain)

                            # Skip tokens with repeated failures or already held
                            if self.should_skip_token(token, chain):
                                logger.info(
                                    f"  Skipping {token}: too many recent failures"
                                )
                                continue
                            if self.is_already_held(token, chain):
                                logger.info(f"  Skipping {token}: already held")
                                continue

                            traded = False

                            if chain == "base" and base_bal > Decimal("0.000001"):
                                # Refresh Base balance per trade so back-to-back buys don't
                                # reuse stale pre-trade balance and overspend.
                                fresh_base_bal = self.get_balance("base")
                                gas_reserve = self.BASE_GAS_RESERVE
                                spendable = fresh_base_bal - gas_reserve
                                if spendable < Decimal("0"):
                                    spendable = Decimal("0")

                                # Trade 50% of spendable ETH (after gas reserve)
                                trade_amount = float(spendable * Decimal("0.5"))

                                # Check if trade is > 0.1 cent (Base L2 gas is ~0.0000009 ETH)
                                if (
                                    trade_amount > 0.0000005
                                ):  # allow tiny Base test trades
                                    logger.info(
                                        f"Trading {trade_amount:.6f} ETH for {token} on Base (fresh balance {fresh_base_bal:.6f})"
                                    )
                                    success = self.execute_base_trade(
                                        token, token_addr, trade_amount
                                    )
                                    if success:
                                        logger.info(f"Successfully bought {token}")
                                        self.record_buy(
                                            token, chain, token_addr, trade_amount
                                        )
                                        active_positions[token] = {
                                            "chain": chain,
                                            "amount": trade_amount,
                                            "entry_price": 0,
                                            "timestamp": time.time(),
                                        }
                                        traded = True
                                    else:
                                        logger.error(f"Failed to buy {token}")
                                        self.record_failed_trade(
                                            token, chain, "Base trade execution failed"
                                        )
                                else:
                                    logger.warning(
                                        f"Trade too small: {trade_amount:.6f} ETH"
                                    )

                            elif chain == "solana" and sol_bal > Decimal("0.002"):
                                # Trade 50% of SOL balance, minus gas reserve
                                sol_spendable = sol_bal - self.SOLANA_GAS_RESERVE
                                if sol_spendable < Decimal("0"):
                                    sol_spendable = Decimal("0")
                                trade_amount = float(sol_spendable * Decimal("0.5"))

                                # Check if trade is > 5 cents
                                if trade_amount > 0.0003:  # ~$0.03 minimum
                                    logger.info(
                                        f"Trading {trade_amount:.6f} SOL for {token} on Solana"
                                    )
                                    sol_mint = token_addr or token
                                    success = self.execute_solana_trade(
                                        token, sol_mint, trade_amount
                                    )
                                    if success:
                                        logger.info(f"Successfully bought {token}")
                                        self.record_buy(
                                            token,
                                            chain,
                                            token_addr or sol_mint,
                                            trade_amount,
                                        )
                                        active_positions[token] = {
                                            "chain": chain,
                                            "amount": trade_amount,
                                            "entry_price": 0,
                                            "timestamp": time.time(),
                                        }
                                        traded = True
                                    else:
                                        logger.error(f"Failed to buy {token}")
                                        self.record_failed_trade(
                                            token,
                                            chain,
                                            "Solana trade execution failed",
                                        )
                                else:
                                    logger.warning(
                                        f"Trade too small: {trade_amount:.6f} SOL"
                                    )

                            if not traded:
                                if chain == "base" and base_bal <= Decimal("0.000001"):
                                    logger.warning(
                                        f"Insufficient Base balance ({base_bal:.8f} ETH) for {token} - need >0.000001 ETH"
                                    )
                                elif chain == "solana" and sol_bal <= Decimal("0.001"):
                                    logger.warning(
                                        f"Insufficient Solana balance ({sol_bal:.6f} SOL) for {token} - need >0.003 SOL"
                                    )

                        elif action == "BUY" and conf < 0.7:
                            logger.debug(
                                f"Skipping {token}: confidence {conf:.2f} < 0.70 threshold"
                            )

                except Exception as e:
                    logger.error(f"Signal error: {e}")
                    import traceback

                    traceback.print_exc()

                # Log funding status if no trades were possible
                if (
                    base_bal < self.BASE_GAS_RESERVE
                    and sol_bal < self.SOLANA_GAS_RESERVE
                ):
                    logger.warning(
                        f"LOW FUNDS - cannot trade on either chain. Base: {base_bal:.8f} ETH, Solana: {sol_bal:.6f} SOL"
                    )
                elif base_bal < self.BASE_GAS_RESERVE and not holdings:
                    logger.info(
                        f"Base balance low ({base_bal:.8f} ETH) and no token holdings to sell"
                    )

                # ==================== BRIDGING OPPORTUNITIES ====================
                # Check if we should bridge between chains
                if base_bal > Decimal("0.0001") and sol_bal < self.SOLANA_GAS_RESERVE:
                    # More ETH than SOL - consider bridging
                    logger.info("Checking bridging opportunities: Base -> Solana")
                    bridge_amount = str(int(float(base_bal) * 0.3 * 1e18))  # 30% of ETH
                    bridge_quote = self.bridge_quote(
                        "base",
                        "solana",
                        "0x4200000000000000000000000000000000000006",
                        bridge_amount,
                    )
                    if bridge_quote:
                        to_amount = bridge_quote.get("estimate", {}).get(
                            "toAmount", "N/A"
                        )
                        logger.info(f"Bridge quote available: {to_amount}")
                        # Execute the bridge
                        if self.execute_bridge(
                            "base",
                            "solana",
                            "0x4200000000000000000000000000000000000006",
                            bridge_amount,
                        ):
                            logger.info("Bridge executed successfully: Base -> Solana")
                            time.sleep(5)  # Wait for bridge to complete
                            sol_bal = self.get_balance("solana")
                            base_bal = self.get_balance("base")
                        else:
                            logger.warning("Bridge execution failed: Base -> Solana")

                elif sol_bal > Decimal("0.003") and base_bal < self.BASE_GAS_RESERVE:
                    # More SOL than ETH - consider bridging
                    logger.info("Checking bridging opportunities: Solana -> Base")
                    bridge_amount = str(int(float(sol_bal) * 0.3 * 1e9))  # 30% of SOL
                    bridge_quote = self.bridge_quote(
                        "solana",
                        "base",
                        "So11111111111111111111111111111111111111112",
                        bridge_amount,
                    )
                    if bridge_quote:
                        to_amount = bridge_quote.get("estimate", {}).get(
                            "toAmount", "N/A"
                        )
                        logger.info(f"Bridge quote available: {to_amount}")
                        # Execute the bridge
                        if self.execute_bridge(
                            "solana",
                            "base",
                            "So11111111111111111111111111111111111111112",
                            bridge_amount,
                        ):
                            logger.info("Bridge executed successfully: Solana -> Base")
                            time.sleep(5)  # Wait for bridge to complete
                            sol_bal = self.get_balance("solana")
                            base_bal = self.get_balance("base")
                        else:
                            logger.warning("Bridge execution failed: Solana -> Base")

                # ==================== LIQUIDITY POOLING ====================
                # Check for liquidity pooling opportunities when we have idle capital
                if base_bal > Decimal("0.0002") and not active_positions:
                    # More than 0.002 ETH and no active positions - consider liquidity
                    logger.info("Checking liquidity pooling opportunities")

                    # Check WETH/USDC pool
                    pool_info = self.get_pool_info(
                        "0x4200000000000000000000000000000000000006",  # WETH
                        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
                        "base",
                    )
                    if pool_info:
                        apr = pool_info.get("apr", 0)
                        liquidity = pool_info.get("liquidity", 0)
                        logger.info(
                            f"WETH/USDC Pool: APR={apr}%, Liquidity=${liquidity:,.0f}"
                        )

                        if (
                            apr > 10 and liquidity > 100000
                        ):  # 10% APR and $100k+ liquidity
                            logger.info("Good liquidity opportunity found!")
                            # Could add liquidity here

                # ==================== LIMIT ORDERS ====================
                # Check if we should place limit orders for existing positions
                for token, position in list(active_positions.items()):
                    if position.get("chain") == "base":
                        # Place limit order to sell at 20% profit
                        entry_price = position.get("entry_price", 0)
                        if entry_price > 0:
                            target_price = str(entry_price * 1.2)  # 20% profit
                            token_addr = self.get_token_address(token, "base")
                            if token_addr:
                                logger.info(
                                    f"Checking limit order for {token} at {target_price}"
                                )
                                order = self.create_limit_order(
                                    token_addr,
                                    "0x4200000000000000000000000000000000000006",  # WETH
                                    str(int(position["amount"] * 1e18)),
                                    target_price,
                                    "base",
                                )
                                if order:
                                    limit_orders[token] = order
                                    logger.info(f"Limit order placed for {token}")

                # ==================== DCA STRATEGIES ====================
                # Check for DCA opportunities (regular purchases of established tokens)
                screener_tokens = self._load_screener_tokens()
                dca_tokens = list(screener_tokens.keys())[
                    :3
                ]  # Top 3 screener tokens for DCA
                if base_bal > Decimal("0.001") and not dca_schedules:
                    # Start DCA if we have funds and no active DCA
                    for token in dca_tokens:
                        token_addr = self.get_token_address(token, "base")
                        if token_addr:
                            dca_amount = str(
                                int(float(base_bal) * 0.1 * 1e18)
                            )  # 10% of balance
                            logger.info(f"Checking DCA for {token}")
                            dca_order = self.create_dca_order(
                                token_addr, dca_amount, 7, "base"
                            )
                            if dca_order:
                                dca_schedules[token] = dca_order
                                logger.info(
                                    f"DCA started for {token}: {dca_amount} wei x 7 days"
                                )
                                break  # Only start one DCA at a time

                time.sleep(300)  # 5 minutes

            except KeyboardInterrupt:
                logger.info("Stopping trader...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(60)


def run_smoke_test(trader: DexAggregatorTrader, chain: str = "both") -> int:
    """Run a minimal real buy/sell round-trip to verify execution paths."""
    ok = True

    if chain in ("base", "both"):
        try:
            base_bal = trader.get_balance("base")
            usdc_base = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
            buy_eth = min(float(base_bal) * 0.4, 0.00002)
            if buy_eth >= 0.000008:
                logger.info(f"[SMOKE][BASE] BUY USDC with {buy_eth:.8f} ETH")
                buy_ok = trader.execute_base_trade("USDC", usdc_base, buy_eth)
                logger.info(f"[SMOKE][BASE] buy_ok={buy_ok}")
                time.sleep(6)
                logger.info("[SMOKE][BASE] SELL 100% USDC back to WETH")
                sell_ok = trader.sell_token_for_eth("USDC", usdc_base, sell_pct=1.0)
                logger.info(f"[SMOKE][BASE] sell_ok={sell_ok}")
                ok = ok and buy_ok and sell_ok
            else:
                logger.warning(
                    f"[SMOKE][BASE] skipped: insufficient Base ETH balance ({base_bal:.8f})"
                )
                ok = False
        except Exception as e:
            logger.error(f"[SMOKE][BASE] failed: {e}")
            ok = False

    if chain in ("solana", "both"):
        try:
            sol_bal = trader.get_balance("solana")
            usdc_sol = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            buy_sol = min(float(sol_bal) * 0.25, 0.001)
            if buy_sol >= 0.0003:
                logger.info(f"[SMOKE][SOL] BUY USDC with {buy_sol:.6f} SOL")
                buy_ok = trader.execute_solana_trade("USDC", usdc_sol, buy_sol)
                logger.info(f"[SMOKE][SOL] buy_ok={buy_ok}")
                time.sleep(6)
                logger.info("[SMOKE][SOL] SELL 50% USDC back to SOL")
                sell_ok = trader.sell_solana_token("USDC", usdc_sol, sell_pct=0.5)
                logger.info(f"[SMOKE][SOL] sell_ok={sell_ok}")
                ok = ok and buy_ok and sell_ok
            else:
                logger.warning(
                    f"[SMOKE][SOL] skipped: insufficient Solana balance ({sol_bal:.6f})"
                )
                ok = False
        except Exception as e:
            logger.error(f"[SMOKE][SOL] failed: {e}")
            ok = False

    logger.info(f"[SMOKE] overall_ok={ok}")
    return 0 if ok else 1


def main():
    import argparse

    parser = argparse.ArgumentParser(description="DEX Aggregator Trader")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run one-shot real buy/sell verification (USDC on selected chain)",
    )
    parser.add_argument(
        "--chain",
        choices=["base", "solana", "both"],
        default="both",
        help="Chain scope for --smoke-test",
    )
    args = parser.parse_args()

    try:
        trader = DexAggregatorTrader()

        logger.info("=" * 60)
        logger.info("DEX Aggregator Trader")
        logger.info("=" * 60)

        if trader.evm_account:
            logger.info(f"EVM: {trader.evm_account.address}")
        if trader.solana_keypair:
            logger.info(f"Solana: {trader.solana_keypair.pubkey()}")

        logger.info(
            "Capabilities: Swaps, Bridging, Liquidity Pooling, Limit Orders, DCA"
        )
        logger.info("=" * 60)

        if args.smoke_test:
            raise SystemExit(run_smoke_test(trader, chain=args.chain))

        trader.run()

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
