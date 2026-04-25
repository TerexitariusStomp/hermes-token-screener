#!/usr/bin/env python3
"""SURVIVAL v23 - MULTICHAIN TRADING
Base: direct Web3 (WETH/Uniswap V3)
Ethereum & Solana: GatewayClientV2 routing
"""

import os, json, time, subprocess, requests, logging, fcntl
from datetime import datetime, timezone
from dotenv import load_dotenv
# TOR proxy - route all external HTTP through SOCKS5
import sys, os
# Override TOR for trading signals — direct connections are faster and more reliable
os.environ["HERMES_TOR_ENABLED"] = "false"
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-token-screener"))
import hermes_screener.tor_config

load_dotenv(os.path.expanduser("~/.hermes/.env"))
from eth_account import Account
from web3 import Web3
from signal_providers import aggregate_signals
from telegram_user import TelegramUser

logging.basicConfig(level=logging.INFO)

# ==================== WALLET CONFIG ====================
pk_base = os.environ.get("WALLET_PRIVATE_KEY_BASE", "")
if not pk_base:
    # Last-resort fallback: read .env directly and parse manually
    env_path = os.path.expanduser("~/.hermes/.env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("WALLET_PRIVATE_KEY_BASE="):
                pk_base = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
if not pk_base or len(pk_base) < 32:
    raise RuntimeError(
        f"FATAL: WALLET_PRIVATE_KEY_BASE is missing/empty (loaded {len(pk_base)} chars) "
        f"from ~/.hermes/.env. Cannot initialize trading account."
    )

pk_ethereum = os.environ.get("WALLET_PRIVATE_KEY_ETHEREUM") or pk_base
solana_wallet_address = os.environ.get("WALLET_ADDRESS_SOLANA", "")

account_base = Account.from_key(pk_base)
account_ethereum = Account.from_key(pk_ethereum)
account = account_base


def get_account(chain: str):
    if chain == "base":
        return account_base
    elif chain in ("ethereum", "mainnet"):
        return account_ethereum
    elif chain == "solana":
        return None
    return account_base


# ==================== PATHS ====================
SF = "/home/terexitarius/.hermes/memories/economic_survival.json"
RS = "/home/terexitarius/trading-system/survival/review.py"
LOCK_FILE = "/home/terexitarius/.hermes/scripts/trading_bot.lock"
MG = 0.00005  # Minimal gas reserve (ETH equiv)

# ==================== TELEGRAM ====================
tg = None
tg_enabled = bool(os.getenv("TELEGRAM_CHAT_ID"))
_LOCK_FD = None

# ==================== CHAIN CONSTANTS ====================
WETH_ADDR = {
    "base": "0x4200000000000000000000000000000000000006",
    "ethereum": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
}
ROUTER_ADDR = {
    "base": "0x2626664c2603336E57B271c5C0b26F421741e481",
    "ethereum": "0xE592427A0AEce92De3Edee1F18E0157C05845b96",
}
UNISWAP_FACTORY_ADDR = {
    "base": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
    "ethereum": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
}
VALID_UNIV3_FEES = (100, 500, 3000, 10000)
CHAIN_ID = {"base": 8453, "ethereum": 1}
NATIVE_DECIMALS = {"base": 18, "ethereum": 18}

# Solana
SOLANA_WSOL = "So11111111111111111111111111111111111111112"
SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://mainnet.helius-rpc.com/?api-key=bb6ff3e9-e38d-4362-9e7a-669a00d497a8")

# Uniswap fee tiers
FEE_MAP = {
    "0x18A8BD1fe17A1BB9FFB39eCD83E9489cfD17a022": 10000,  # ANDY (1%)
}
FEE_DEFAULT = 3000


# ==================== GATEWAY CLIENT ====================
class GatewayClient:
    def __init__(self):
        self.base_url = "http://localhost:15888"
        self.session = requests.Session()

    def _post(self, endpoint: str, payload: dict = None):
        try:
            r = self.session.post(
                f"{self.base_url}{endpoint}", json=payload or {}, timeout=30
            )
            return r.json()
        except Exception as e:
            logging.error(f"[Gateway] {endpoint} failed: {e}")
            return {"error": str(e)}

    def ethereum_balances(self, address: str, network: str = "base"):
        return self._post("/chains/ethereum/balances", {"address": address, "network": network})

    def solana_balances(self, address: str):
        return self._post("/chains/solana/balances", {"address": address})

    def ethereum_approve(self, address: str, spender: str, token: str, amount: str, network: str = "base"):
        return self._post(
            "/chains/ethereum/approve",
            {"address": address, "spender": spender, "token": token, "amount": amount, "network": network},
        )

    def uniswap_execute_swap(
        self,
        chain: str,
        address: str,
        base: str,
        quote: str,
        amount: str,
        side: str,
        slippage: float = 0.5,
        fee_tier: float = None,
        max_hops: int = None,
    ):
        payload = {
            "chain": chain,
            "address": address,
            "base": base,
            "quote": quote,
            "amount": amount,
            "side": side,
            "slippage": slippage,
        }
        if fee_tier is not None:
            payload["feeTier"] = fee_tier
        if max_hops is not None:
            payload["maxHops"] = max_hops
        return self._post("/connectors/uniswap/router/execute-swap", payload)

    def jupiter_execute_swap(
        self, wallet_address: str, base_token: str, quote_token: str, amount: float, side: str = "BUY", slippage_pct: float = 5.0, network: str = "mainnet-beta"
    ):
        payload = {
            "walletAddress": wallet_address,
            "network": network,
            "baseToken": base_token,
            "quoteToken": quote_token,
            "amount": amount,
            "side": side,
            "slippagePct": slippage_pct,
        }
        return self._post("/connectors/jupiter/router/execute-swap", payload)


gw_client = GatewayClient()

# Jupiter Direct API (bypasses gateway container for Solana swaps)
JUPITER_API_KEY = os.environ.get("JUPITER_API_KEY", "")
JUPITER_BASE_URL = "https://api.jup.ag/swap/v1"  # v1 quote endpoint (compatible with /swap-instructions)


def jupiter_direct_swap(
    wallet_address: str,
    base_token: str,
    quote_token: str,
    amount: float,
    side: str = "BUY",
    slippage_bps: int = 100,
) -> dict:
    """Direct Jupiter API swap — quote via urllib, build+sign+send via solana_adapter."""
    try:
        import json as _json
        import urllib.request

        amt_lamports = int(amount * 1e9)
        headers = {"User-Agent": "Mozilla/5.0"}
        if JUPITER_API_KEY:
            headers["x-api-key"] = JUPITER_API_KEY

        # Step 1: GET /order — get quote
        params = (
            f"inputMint={base_token}&outputMint={quote_token}"
            f"&amount={amt_lamports}&slippageBps={slippage_bps}&side={side}"
        )
        url = f"{JUPITER_BASE_URL}/order?{params}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status != 200:
                return {"error": f"Jupiter order failed: {r.status}"}
            quote = _json.loads(r.read())

        if not quote.get("swapType"):
            return {"error": f"Jupiter order returned no route: {quote}"}

        # Step 2: Build + sign + send via solana_adapter (which uses /swap-instructions v1)
        from solana_adapter import SolanaProgramAdapter as SolanaAdapter

        adapter = SolanaAdapter(
            rpc_url=os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
            private_key=os.environ.get("WALLET_PRIVATE_KEY_SOLANA", ""),
        )
        tx = adapter.jupiter_build_tx(quote, wrap_unwrap=False)
        if not tx:
            return {"error": "Jupiter build_tx returned None"}

        sig = adapter.send_tx(tx)
        if sig:
            return {"success": True, "txid": sig}
        return {"error": "send_tx returned None"}

    except Exception as e:
        return {"error": f"Jupiter direct swap exception: {e}"}


def _parse_jupiter_instruction(swap_data: dict):
    """Parse a Jupiter swap instruction into a transaction dict."""
    try:
        if isinstance(swap_data, str):
            swap_data = json.loads(swap_data)
        # Jupiter v6 returns {signers: [], instructions: [], lookupTables: []}
        keys = swap_data.get("keys", [])
        program_id = swap_data.get("programId", "")
        data = swap_data.get("data", "")
        instructions = swap_data.get("instructions", [])
        if instructions:
            # newer format
            return {
                "keys": keys,
                "program_id": program_id,
                "data": data,
                "instructions": instructions,
            }
        return swap_data
    except Exception:
        return None


# ==================== NOTIFY / LOG ====================
def tg_notify(msg: str):
    global tg, tg_enabled
    if not tg_enabled:
        return
    if tg is None:
        try:
            os.environ.setdefault("TG_RETRY_ATTEMPTS", "1")
            tg = TelegramUser()
            started = tg.start()
            if not started:
                l("Telegram disabled: session unavailable or unauthorized")
                tg_enabled = False
                return
        except Exception as e:
            l(f"Telegram init failed: {e}")
            tg_enabled = False
            return
    try:
        ok = tg.send_message(msg)
        if not ok:
            l("Telegram send returned False; disabling notifications for this run")
            tg_enabled = False
    except Exception as e:
        l(f"Telegram send failed: {e}")
        tg_enabled = False


def l(m: str):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {m}")


def ep() -> float:
    try:
        r = requests.get(
            timeout=8,
        )
        return float(r.json()["ethereum"]["usd"])
    except:
        return 2300.0


def acquire_singleton_lock() -> bool:
    """Prevent multiple concurrent bot instances (cron-safe)."""
    global _LOCK_FD
    try:
        _LOCK_FD = open(LOCK_FILE, "w")
        fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_FD.write(str(os.getpid()))
        _LOCK_FD.flush()
        return True
    except OSError:
        l("Another trading_bot instance is already running; exiting.")
        return False


# ==================== PROVIDER HELPERS ====================
def gw():
    for u in [
        "https://mainnet.base.org",
        "https://developer-access-mainnet.base.org",
        "https://base.llamarpc.com",
        "https://base.publicnode.com",
        "https://base-rpc.publicnode.com",
        "https://base-mainnet.g.alchemy.com/v2/demo",
    ]:
        try:
            w = Web3(Web3.HTTPProvider(u, request_kwargs={"timeout": 8}))
            if w.is_connected():
                _ = w.eth.block_number
                return w
        except:
            pass
    return None


def gw_eth():
    for u in [
        "https://mainnet.eth.llamarpc.com",
        "https://eth.llamarpc.com",
        "https://mainnet.g.alchemy.com/v2/demo",
    ]:
        try:
            w = Web3(Web3.HTTPProvider(u, request_kwargs={"timeout": 8}))
            if w.is_connected():
                return w
        except:
            pass
    return None


def get_signed_raw_tx(signed_tx):
    raw = getattr(signed_tx, "raw_transaction", None)
    if raw is None:
        raw = getattr(signed_tx, "rawTransaction", None)
    if raw is None:
        raise ValueError("Signed transaction missing raw bytes")
    return raw


def get_allowance(w: Web3, token_addr: str, owner: str, spender: str) -> int:
    try:
        c = w.eth.contract(
            address=token_addr,
            abi=[
                {
                    "inputs": [
                        {"name": "owner", "type": "address"},
                        {"name": "spender", "type": "address"},
                    ],
                    "name": "allowance",
                    "outputs": [{"type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                }
            ],
        )
        return c.functions.allowance(owner, spender).call()
    except Exception as e:
        l(f"Allowance read error: {e}")
        return 0


def ensure_allowance_base(
    w: Web3, token_addr: str, spender: str, needed_wei: int
) -> bool:
    try:
        allowance = get_allowance(w, token_addr, account.address, spender)
        if allowance < needed_wei:
            l(f"Base: approving {token_addr} for {spender}")
            if not approve(w, token_addr, spender, needed_wei):
                return False
            allowance = get_allowance(w, token_addr, account.address, spender)
            return allowance >= needed_wei
        return True
    except Exception as e:
        l(f"Base allowance error: {e}")
        return False


def ensure_allowance_ethereum(
    w: Web3, token_addr: str, spender: str, needed_wei: int
) -> bool:
    try:
        allowance = get_allowance(w, token_addr, account.address, spender)
        if allowance < needed_wei:
            l(f"Ethereum: approving {token_addr} via Gateway")
            resp = gw_client.ethereum_approve(
                address=account.address,
                spender=spender,
                token=token_addr,
                amount=str(needed_wei),
            )
            if resp.get("error"):
                l(f"Gateway approve error: {resp['error']}")
                return False
            time.sleep(2)
            allowance = get_allowance(w, token_addr, account.address, spender)
            return allowance >= needed_wei
        return True
    except Exception as e:
        l(f"Ethereum allowance error: {e}")
        return False


# ==================== BALANCE HELPERS ====================
def get_native_balance(chain: str) -> float:
    global account
    if chain == "base":
        w = gw()
        if not w:
            return 0.0
        bal_wei = w.eth.get_balance(account.address)
        return float(w.from_wei(bal_wei, "ether"))
    elif chain == "ethereum":
        w = gw_eth()
        if not w:
            return 0.0
        bal_wei = w.eth.get_balance(account.address)
        return float(w.from_wei(bal_wei, "ether"))
    elif chain == "solana":
        addr = solana_wallet_address
        if not addr:
            return 0.0
        # Try Gateway first
        resp = gw_client.solana_balances(address=addr)
        if "error" not in resp:
            bal = resp.get("balances", {})
            # Gateway v2 returns {"SOL": amount}, v1 returns [{"symbol":"SOL","balance":amount}]
            if isinstance(bal, dict):
                sol_amt = bal.get("SOL", 0)
                # Gateway returns SOL units (not lamports); only divide if it looks like lamports
                val = float(sol_amt)
                return val / 1e9 if val > 100 else val
            for b in bal:
                if b.get("symbol") == "SOL":
                    val = float(b.get("balance", 0))
                    return val / 1e9 if val > 100 else val
        # Fallback: direct Solana RPC query
        try:
            rpc_url = SOLANA_RPC_URL
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [addr],
            }
            r = requests.post(rpc_url, json=payload, timeout=10)
            data = r.json()
            lamports = data.get("result", {}).get("value", 0)
            return lamports / 1e9
        except Exception:
            return 0.0
    return 0.0


def get_token_balance(chain: str, token_addr: str, decimals: int = None) -> float:
    global account
    if chain == "base":
        w = gw()
        if not w:
            return 0.0
        try:
            c = w.eth.contract(
                address=token_addr,
                abi=[
                    {
                        "inputs": [{"name": "owner", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"type": "uint256"}],
                        "stateMutability": "view",
                        "type": "function",
                    },
                    {
                        "inputs": [],
                        "name": "decimals",
                        "outputs": [{"type": "uint8"}],
                        "stateMutability": "view",
                        "type": "function",
                    },
                ],
            )
            if decimals is None:
                dec = c.functions.decimals().call()
            else:
                dec = decimals
            bal_wei = c.functions.balanceOf(account.address).call()
            return bal_wei / (10**dec)
        except:
            return 0.0
    elif chain == "ethereum":
        w = gw_eth()
        if not w:
            return 0.0
        try:
            c = w.eth.contract(
                address=token_addr,
                abi=[
                    {
                        "inputs": [{"name": "owner", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"type": "uint256"}],
                        "stateMutability": "view",
                        "type": "function",
                    },
                    {
                        "inputs": [],
                        "name": "decimals",
                        "outputs": [{"type": "uint8"}],
                        "stateMutability": "view",
                        "type": "function",
                    },
                ],
            )
            if decimals is None:
                dec = c.functions.decimals().call()
            else:
                dec = decimals
            bal_wei = c.functions.balanceOf(account.address).call()
            return bal_wei / (10**dec)
        except:
            return 0.0
    elif chain == "solana":
        addr = solana_wallet_address
        if not addr:
            return 0.0
        rpc_url = SOLANA_RPC_URL
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [addr, {"mint": token_addr}, {"encoding": "jsonParsed"}],
        }
        try:
            r = requests.post(rpc_url, json=body, timeout=8)
            if r.status_code == 200:
                resp = r.json()
                result = resp.get("result", {})
                total = 0.0
                for acc in result.get("value", []):
                    parsed = acc.get("account", {}).get("data", {}).get("parsed", {})
                    info = parsed.get("info", {})
                    amt_str = info.get("tokenAmount", {}).get("amount")
                    if amt_str:
                        amt = float(amt_str)
                        dec = info.get("tokenAmount", {}).get("decimals", 0)
                        total += amt / (10**dec) if dec else amt
                return total
        except Exception as e:
            l(f"Solana balance error: {e}")
        return 0.0
    return 0.0


# ==================== GAS & EXECUTION (BASE) ====================
def get_gas_price(w):
    try:
        return w.to_wei(0.2, "gwei")
    except Exception:
        return w.to_wei(0.2, "gwei")


def ensure_gas_reserve_base(w, min_native_required=0.00005) -> bool:
    """If native balance is below threshold, unwrap a small amount of WETH to cover gas."""
    try:
        native_bal = get_native_balance("base")
        if native_bal >= min_native_required:
            return True
        # Need to unwrap WETH
        weth_bal = get_token_balance("base", WETH_ADDR["base"])
        # Include extra margin to offset unwrap tx gas itself.
        unwrap_amount = min(min_native_required - native_bal + 0.00004, weth_bal)
        if unwrap_amount <= 0:
            l(f"Gas reserve: insufficient WETH to unwrap (have {weth_bal:.6f})")
            return False
        # Unwrap via WETH withdraw
        weth = w.eth.contract(
            address=WETH_ADDR["base"],
            abi=[
                {
                    "inputs": [{"name": "amount", "type": "uint256"}],
                    "name": "withdraw",
                    "outputs": [],
                    "stateMutability": "nonpayable",
                    "type": "function",
                }
            ],
        )
        amt_wei = int(unwrap_amount * 1e18)
        tx = weth.functions.withdraw(amt_wei).build_transaction(
            {
                "from": account.address,
                "nonce": w.eth.get_transaction_count(account.address, "pending"),
                "gas": 120000,
                "maxFeePerGas": get_gas_price(w),
                "maxPriorityFeePerGas": get_gas_price(w),
            }
        )
        signed = account.sign_transaction(tx)
        tx_hash = w.eth.send_raw_transaction(get_signed_raw_tx(signed))
        l(f"Unwrapped {unwrap_amount:.6f} WETH for gas: {tx_hash.hex()}")
        receipt = w.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt and receipt.status == 1:
            new_native = get_native_balance("base")
            l(f"Post-unwrap native balance: {new_native:.6f}")
            return new_native >= min_native_required
        return False
    except Exception as e:
        l(f"ensure_gas_reserve_base error: {e}")
        return False



def wrap_eth(w: Web3, amount_eth: float, chain: str = "base") -> bool:
    """Wrap native ETH to WETH via direct Web3 call."""
    try:
        acct = get_account(chain)
        weth_addr = WETH_ADDR.get(chain)
        if not weth_addr:
            l(f"No WETH address for chain {chain}")
            return False
        weth = w.eth.contract(
            address=weth_addr,
            abi=[
                {
                    "inputs": [],
                    "name": "deposit",
                    "outputs": [],
                    "stateMutability": "payable",
                    "type": "function",
                }
            ],
        )
        amt_wei = int(amount_eth * 1e18)
        tx = weth.functions.deposit().build_transaction(
            {
                "from": acct.address,
                "nonce": w.eth.get_transaction_count(acct.address, "pending"),
                "gas": 80000,
                "maxFeePerGas": get_gas_price(w),
                "maxPriorityFeePerGas": get_gas_price(w),
                "value": amt_wei,
            }
        )
        signed = acct.sign_transaction(tx)
        tx_hash = w.eth.send_raw_transaction(get_signed_raw_tx(signed))
        l(f"Wrap ETH->WETH tx: {tx_hash.hex()}")
        receipt = w.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt and receipt.status == 1:
            l(f"Wrapped {amount_eth:.6f} ETH -> WETH successfully")
            return True
        else:
            l("Wrap ETH->WETH failed (receipt status != 1)")
            return False
    except Exception as e:
        l(f"wrap_eth error: {e}")
        return False


def approve(w, token_addr, spender, amt_wei):
    try:
        c = w.eth.contract(
            address=token_addr,
            abi=[
                {
                    "inputs": [
                        {"name": "s", "type": "address"},
                        {"name": "a", "type": "uint256"},
                    ],
                    "name": "approve",
                    "outputs": [{"type": "bool"}],
                    "stateMutability": "nonpayable",
                    "type": "function",
                }
            ],
        )
        gas_limit = 50000
        gas_price = get_gas_price(w)
        max_priority = w.to_wei(0.01, "gwei")
        tx = c.functions.approve(spender, amt_wei).build_transaction(
            {
                "from": account.address,
                "nonce": w.eth.get_transaction_count(account.address, "pending"),
                "gas": gas_limit,
                "maxFeePerGas": gas_price + max_priority,
                "maxPriorityFeePerGas": max_priority,
            }
        )
        signed = account.sign_transaction(tx)
        tx_hash = w.eth.send_raw_transaction(get_signed_raw_tx(signed))
        l(f"Approve tx: {tx_hash.hex()}")
        w.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return True
    except Exception as e:
        l(f"Approve FAIL: {e}")
        return False


def swap_w2t(w, token_addr, amt_wei, fee):
    try:
        router = ROUTER_ADDR["base"]
        c = w.eth.contract(
            address=router,
            abi=[
                {
                    "inputs": [
                        {"name": "tokenIn", "type": "address"},
                        {"name": "tokenOut", "type": "address"},
                        {"name": "fee", "type": "uint24"},
                        {"name": "recipient", "type": "address"},
                        {"name": "deadline", "type": "uint256"},
                        {"name": "amountIn", "type": "uint256"},
                        {"name": "amountOutMinimum", "type": "uint256"},
                        {"name": "sqrtPriceLimitX96", "type": "uint256"},
                    ],
                    "name": "exactInputSingle",
                    "outputs": [{"type": "uint256"}],
                    "stateMutability": "nonpayable",
                    "type": "function",
                }
            ],
        )
        deadline = int(time.time()) + 300
        params = (
            WETH_ADDR["base"],
            token_addr,
            fee,
            account.address,
            deadline,
            amt_wei,
            0,
            0,
        )
        tx = c.functions.exactInputSingle(*params).build_transaction(
            {
                "from": account.address,
                "nonce": w.eth.get_transaction_count(account.address, "pending"),
                "gas": 250000,
                "maxFeePerGas": get_gas_price(w),
                "maxPriorityFeePerGas": get_gas_price(w),
            }
        )
        signed = account.sign_transaction(tx)
        tx_hash = w.eth.send_raw_transaction(get_signed_raw_tx(signed))
        l(f"Swap W2T tx: {tx_hash.hex()}")
        receipt = w.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        return receipt and receipt.status == 1
    except Exception as e:
        l(f"Swap W2T FAIL: {e}")
        return False


def swap_t2w(w, token_addr, amt_wei, fee):
    try:
        router = ROUTER_ADDR["base"]
        c = w.eth.contract(
            address=router,
            abi=[
                {
                    "inputs": [
                        {"name": "tokenIn", "type": "address"},
                        {"name": "tokenOut", "type": "address"},
                        {"name": "fee", "type": "uint24"},
                        {"name": "recipient", "type": "address"},
                        {"name": "deadline", "type": "uint256"},
                        {"name": "amountIn", "type": "uint256"},
                        {"name": "amountOutMinimum", "type": "uint256"},
                        {"name": "sqrtPriceLimitX96", "type": "uint256"},
                    ],
                    "name": "exactInputSingle",
                    "outputs": [{"type": "uint256"}],
                    "stateMutability": "nonpayable",
                    "type": "function",
                }
            ],
        )
        deadline = int(time.time()) + 300
        params = (
            token_addr,
            WETH_ADDR["base"],
            fee,
            account.address,
            deadline,
            amt_wei,
            0,
            0,
        )
        tx = c.functions.exactInputSingle(*params).build_transaction(
            {
                "from": account.address,
                "nonce": w.eth.get_transaction_count(account.address, "pending"),
                "gas": 250000,
                "maxFeePerGas": get_gas_price(w),
                "maxPriorityFeePerGas": get_gas_price(w),
            }
        )
        signed = account.sign_transaction(tx)
        tx_hash = w.eth.send_raw_transaction(get_signed_raw_tx(signed))
        l(f"Swap T2W tx: {tx_hash.hex()}")
        receipt = w.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        return receipt and receipt.status == 1
    except Exception as e:
        l(f"Swap T2W FAIL: {e}")
        return False


# ==================== OPENOCEAN NATIVE ETH SWAP (no wrap needed) ====================
OPENOCEAN_API = "https://open-api.openocean.finance/v3"
NATIVE_ETH = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

def openocean_eth_swap(w, in_token: str, amount_wei: int, gas_price_gwei: float = None) -> bool:
    """
    Swap native ETH directly for any token via OpenOcean on Base.
    No WETH wrapping needed. Works for any ERC20 on Base.
    """
    try:
        from web3 import Web3
        chain_id = 8453

        if gas_price_gwei is None:
            gas_price_gwei = max(float(w.manager.request_blocking("eth_gasPrice", [])[-2:]) / 1e9, 0.01)

        slippage_bps = 50  # 0.5% slippage
        referrer = "0x0000000000000000000000000000000000000000"

        payload = {
            "inTokenAddress": NATIVE_ETH,
            "outTokenAddress": in_token,
            "amount": str(amount_wei),
            "gasPrice": str(int(gas_price_gwei * 1e9)),
            "slippage": slippage_bps,
            "referrer": referrer,
            "receiver": account.address,
        }

        # Get swap tx data
        resp = requests.get(f"{OPENOCEAN_API}/{chain_id}/quote", params=payload, timeout=15)
        data = resp.json().get("data", {})
        if not data:
            l(f"OpenOcean: no quote — {resp.text[:200]}")
            return False

        out_amt = int(data.get("outAmount", 0))
        l(f"OpenOcean quote: {out_amt} target tokens")

        if out_amt == 0:
            l("OpenOcean: zero output, aborting")
            return False

        min_out = int(out_amt * 0.95)  # 5% safety margin

        swap_tx = data.get("tx", {})
        tx_params = {
            "from": account.address,
            "to": Web3.to_checksum_address(swap_tx.get("to", "0x0000000000000000000000000000000000000000")),
            "data": swap_tx.get("data", "0x"),
            "value": amount_wei,
            "nonce": w.eth.get_transaction_count(account.address, "pending"),
            "gas": 500000,
            "maxFeePerGas": int(gas_price_gwei * 1.2 * 1e9),
            "maxPriorityFeePerGas": int(gas_price_gwei * 1e9),
            "chainId": chain_id,
        }

        # Estimate gas
        try:
            estimated = w.eth.estimate_gas(tx_params)
            tx_params["gas"] = int(estimated * 1.3)
        except:
            pass

        signed = account.sign_transaction(tx_params)
        raw = get_signed_raw_tx(signed)
        tx_hash = w.eth.send_raw_transaction(raw)
        l(f"OpenOcean ETH swap tx: {tx_hash.hex()}")
        receipt = w.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        ok = receipt and receipt.status == 1
        l(f"OpenOcean swap {'OK' if ok else 'FAILED'}")
        return ok

    except Exception as e:
        l(f"OpenOcean ETH swap FAIL: {e}")
        return False


# ==================== TOKEN RESOLUTION & METADATA ====================
def resolve_token(sym: str, chain: str = "base") -> str | None:
    try:
        if sym.startswith("0x") and len(sym) == 42:
            return sym
        url = f"https://api.dexscreener.com/latest/dex/search?q={sym}"
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        pairs = r.json().get("pairs", [])
        chain_norm = {
            "base": "base",
            "ethereum": "ethereum",
            "mainnet": "ethereum",
            "eth": "ethereum",
            "solana": "solana",
        }.get(chain, chain)
        for p in pairs:
            if p.get("chainId") != chain_norm:
                continue
            base_tok = p.get("baseToken", {})
            if base_tok.get("symbol", "").upper() == sym.upper():
                return base_tok.get("address")
    except Exception as e:
        l(f"resolve_token error: {e}")
    return None


def normalize_fee_tier(raw_fee) -> int:
    """Normalize fee inputs (bps, percent, strings) to valid Uniswap v3 fee tiers."""
    if raw_fee is None:
        return FEE_DEFAULT
    try:
        f = float(raw_fee)
        if f in VALID_UNIV3_FEES:
            return int(f)
        # Some APIs return percent (e.g. 1 => 1%), map to fee tier units.
        if 0 < f <= 1:
            candidate = int(round(f * 10000))
            if candidate in VALID_UNIV3_FEES:
                return candidate
        if 1 < f <= 100:
            candidate = int(round(f * 10000 / 100))
            if candidate in VALID_UNIV3_FEES:
                return candidate
    except Exception:
        pass
    return FEE_DEFAULT


def discover_uniswap_v3_fee(
    chain: str, token_addr: str, preferred_fee: int | None = None
) -> int:
    """Discover the actual fee tier by checking pool existence on-chain."""
    if chain not in ("base", "ethereum"):
        return FEE_DEFAULT
    w = gw() if chain == "base" else gw_eth()
    if not w:
        return preferred_fee if preferred_fee in VALID_UNIV3_FEES else FEE_DEFAULT
    try:
        factory = w.eth.contract(
            address=UNISWAP_FACTORY_ADDR[chain],
            abi=[
                {
                    "inputs": [
                        {"name": "tokenA", "type": "address"},
                        {"name": "tokenB", "type": "address"},
                        {"name": "fee", "type": "uint24"},
                    ],
                    "name": "getPool",
                    "outputs": [{"type": "address"}],
                    "stateMutability": "view",
                    "type": "function",
                }
            ],
        )
        token_in = Web3.to_checksum_address(WETH_ADDR[chain])
        token_out = Web3.to_checksum_address(token_addr)
        candidate_fees = []
        mapped = None
        for k, v in FEE_MAP.items():
            if str(k).lower() == str(token_addr).lower():
                mapped = v
                break
        # Explicit map wins (manual overrides from verified executions).
        if mapped in VALID_UNIV3_FEES:
            candidate_fees.append(mapped)
        if preferred_fee in VALID_UNIV3_FEES and preferred_fee not in candidate_fees:
            candidate_fees.append(preferred_fee)
        for fee in VALID_UNIV3_FEES:
            if fee not in candidate_fees:
                candidate_fees.append(fee)

        zero_addr = "0x0000000000000000000000000000000000000000"
        for fee in candidate_fees:
            pool = factory.functions.getPool(token_in, token_out, fee).call()
            if pool and str(pool).lower() != zero_addr:
                return fee
    except Exception as e:
        l(f"Fee discovery error on {chain}: {e}")

    if preferred_fee in VALID_UNIV3_FEES:
        return preferred_fee
    return FEE_DEFAULT


def fetch_token_metadata(token_addr: str, chain: str = "base"):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}"
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            pairs = data.get("pairs", [])
            filtered = [p for p in pairs if p.get("chainId") == chain]
            if not filtered:
                filtered = pairs
            if filtered:
                # Prefer Uniswap pools for chains we execute through Uniswap.
                if chain in ("base", "ethereum"):
                    uni = [
                        p
                        for p in filtered
                        if "uniswap" in str(p.get("dexId", "")).lower()
                    ]
                    if uni:
                        filtered = uni
                # Then prefer deepest liquidity pair for better price/fee metadata.
                filtered.sort(
                    key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
                    reverse=True,
                )
                p = filtered[0]
                base_tok = p.get("baseToken", {})
                decimals = base_tok.get("decimals")
                if decimals is None:
                    decimals = 18
                fee_hint = normalize_fee_tier(p.get("fee"))
                fee = discover_uniswap_v3_fee(chain, token_addr, fee_hint)
                return {
                    "price_usd": float(p.get("priceUsd", 0)),
                    "volume_h24": p.get("volume", {}).get("h24", 0),
                    "liquidity_usd": p.get("liquidity", {}).get("usd", 0),
                    "decimals": int(decimals),
                    "fee": int(fee),
                    "dex": p.get("dexId"),
                }
    except Exception as e:
        l(f"fetch_token_metadata error: {e}")
    return {}


def unwrap_wsol():
    """Close WSOL ATA, converting any WSOL dust back to native SOL."""
    try:
        from solana_adapter import SolanaProgramAdapter
        adapter = SolanaProgramAdapter()
        adapter.close_wsol_ata()
    except Exception:
        pass





# ==================== SOLANA VENUE HELPERS ====================
def _is_pumpfun_token_solana(mint: str) -> dict | None:
    """Return pump.fun token info dict if mint is a pump.fun token, else None."""
    rpc = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    try:
        cmd = [PUMPFUN_CLI, "--json", "--rpc", rpc, "info", mint]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=dict(os.environ))
        if result.returncode != 0:
            err_file = os.path.expanduser("~/.hermes/logs/pumpfun_err.txt")
            with open(err_file, "w") as f:
                f.write(f"RC={result.returncode}\nSTDOUT={result.stdout[:200]}\nSTDERR={result.stderr}")
            # Retry once with public RPC as fallback on 429 (rate limit)
            if "429" in result.stderr or result.returncode != 0:
                fallback_rpc = "https://api.mainnet-beta.solana.com"
                cmd_fallback = [PUMPFUN_CLI, "--json", "--rpc", fallback_rpc, "info", mint]
                r2 = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=30, env=dict(os.environ))
                if r2.returncode == 0 and r2.stdout.strip():
                    try:
                        return json.loads(r2.stdout)
                    except json.JSONDecodeError:
                        pass
            l(f"[Pump] pumpfun failed rc={result.returncode}, full error in {err_file}")
            return None
        info = json.loads(result.stdout)
        if info.get("bonding_curve") or info.get("graduated") is not None:
            return info
        return None
    except Exception as e:
        logging.warning(f"[Pump] _is_pumpfun_token_solana exception: {e}")
        return None


def _execute_pumpfun_solana_buy(
    token_addr: str,
    symbol: str,
    amount_sol: float,
    wallet_addr: str,
    pump_info: dict,
) -> dict:
    """Buy via direct PumpSwap (graduated tokens only)."""
    if not pump_info.get("graduated"):
        return {"success": False, "error": "Token not graduated; cannot buy via PumpSwap"}
    try:
        from solana_adapter import SolanaProgramAdapter as SolanaAdapter

        adapter = SolanaAdapter(
            rpc_url=os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
            private_key=os.environ.get("WALLET_PRIVATE_KEY_SOLANA", ""),
        )
        txid = adapter.pumpswap_buy(token_addr, amount_sol)
        if txid:
            return {"success": True, "output": f"Bought {symbol} for {amount_sol:.4f} SOL via PumpSwap", "txid": txid}
        return {"success": False, "error": "pumpswap_buy returned None"}
    except Exception as e:
        return {"success": False, "error": f"pumpswap_buy exception: {e}"}


def _execute_pumpfun_solana_sell(token_addr: str, symbol: str, wallet_addr: str, pump_info: dict) -> dict:
    """Sell via direct PumpSwap (graduated tokens only)."""
    if not pump_info.get("graduated"):
        return {"success": False, "error": "Token not graduated; cannot sell via PumpSwap"}
    try:
        from solana_adapter import SolanaProgramAdapter as SolanaAdapter

        adapter = SolanaAdapter(
            rpc_url=os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
            private_key=os.environ.get("WALLET_PRIVATE_KEY_SOLANA", ""),
        )
        bal = adapter.get_token_balance(token_addr)
        if bal <= 0:
            return {"success": False, "error": "No token balance to sell"}
        txid = adapter.pumpswap_sell(token_addr, bal)
        if txid:
            return {"success": True, "output": f"Sold {symbol} via PumpSwap", "txid": txid}
        return {"success": False, "error": "pumpswap_sell returned None"}
    except Exception as e:
        return {"success": False, "error": f"pumpswap_sell exception: {e}"}


def _execute_raydium_solana_buy(token_addr: str, amount_sol: float, wallet_addr: str) -> tuple[bool, str]:
    """Execute Solana buy via Raydium CPMM HTTP API.

    Returns (success: bool, message: str).
    """
    try:
        from solana_adapter import SolanaProgramAdapter
    except Exception as e:
        return False, f"solana_adapter import failed: {e}"

    try:
        adapter = SolanaProgramAdapter()
    except Exception as e:
        return False, f"SolanaProgramAdapter init failed: {e}"

    # Get Raydium quote
    try:
        quote = adapter.raydium_cpmm_quote(
            input_mint="So11111111111111111111111111111111111111112",  # WSOL
            output_mint=token_addr,
            amount=int(amount_sol * 1e9),
            slippage_bps=100,
        )
    except Exception as e:
        return False, f"Raydium quote failed: {e}"

    if not quote:
        return False, "Raydium quote returned empty"

    # Build and send transaction
    try:
        tx = adapter.raydium_build_tx(quote)
        if not tx:
            return False, "Raydium tx build returned None"
        sig = adapter.send_tx(tx)
        if not sig:
            return False, "Raydium send_tx returned None"
        confirmed = adapter.confirm_tx(sig)
        if not confirmed:
            return False, f"Raydium tx not confirmed: {sig[:16]}..."
        return True, f"Bought via Raydium CPMM, amount={amount_sol:.4f} SOL, tx={sig[:16]}..."
    except Exception as e:
        return False, f"Raydium send failed: {e}"


def _execute_raydium_solana_sell(token_addr: str, token_amount: float, wallet_addr: str, decimals: int) -> tuple[bool, str]:
    """Execute Solana sell via Raydium CPMM HTTP API.

    Returns (success: bool, message: str).
    """
    try:
        from solana_adapter import SolanaProgramAdapter
    except Exception as e:
        return False, f"solana_adapter import failed: {e}"

    try:
        adapter = SolanaProgramAdapter()
    except Exception as e:
        return False, f"SolanaProgramAdapter init failed: {e}"

    try:
        quote = adapter.raydium_cpmm_quote(
            input_mint=token_addr,
            output_mint="So11111111111111111111111111111111111111112",  # WSOL
            amount=int(token_amount * (10 ** decimals)),
            slippage_bps=100,
        )
    except Exception as e:
        return False, f"Raydium quote failed: {e}"

    if not quote:
        return False, "Raydium quote returned empty"

    try:
        tx = adapter.raydium_build_tx(quote)
        if not tx:
            return False, "Raydium tx build returned None"
        sig = adapter.send_tx(tx)
        if not sig:
            return False, "Raydium send_tx returned None"
        confirmed = adapter.confirm_tx(sig)
        if not confirmed:
            return False, f"Raydium tx not confirmed: {sig[:16]}..."
        return True, f"Sold via Raydium CPMM, tx={sig[:16]}..."
    except Exception as e:
        return False, f"Raydium send failed: {e}"


# ==================== EXECUTION DISPATCH ====================
def execute_buy(
    chain: str, token_addr: str, amount_native: float, metadata: dict
) -> bool:
    global account
    account = get_account(chain)
    fee = metadata.get("fee", FEE_DEFAULT)
    if chain == "base":
        w = gw()
        if not w:
            return False
        weth = WETH_ADDR["base"]
        weth_bal = get_token_balance("base", weth)
        if weth_bal < amount_native:
            native_bal = get_native_balance("base")
            gas_reserve = GAS_RESERVE.get("base", 0.00005)
            if native_bal >= amount_native + gas_reserve:
                l(f"WETH low ({weth_bal:.6f}); wrapping {amount_native:.6f} ETH -> WETH")
                if not wrap_eth(w, amount_native, chain="base"):
                    l("ETH->WETH wrap failed")
                    return False
            else:
                l(f"Insufficient WETH and ETH: have WETH={weth_bal:.6f}, ETH={native_bal:.6f}, need {amount_native:.6f}")
                return False
        if not ensure_gas_reserve_base(
            w, min_native_required=GAS_RESERVE.get("base", 0.00005)
        ):
            l("Base gas reserve unavailable; skipping buy")
            return False
        amt_wei = int(amount_native * 1e18)
        if not ensure_allowance_base(w, weth, ROUTER_ADDR["base"], amt_wei):
            l("WETH allowance not set")
            return False
        return swap_w2t(w, token_addr, amt_wei, fee)

    elif chain == "ethereum":
        w = gw_eth()
        if not w:
            return False
        weth = WETH_ADDR["ethereum"]
        weth_bal = get_token_balance("ethereum", weth)
        if weth_bal < amount_native:
            native_bal = get_native_balance("ethereum")
            gas_reserve = GAS_RESERVE.get("ethereum", 0.001)
            if native_bal >= amount_native + gas_reserve:
                l(f"WETH low ({weth_bal:.6f}); wrapping {amount_native:.6f} ETH -> WETH on Ethereum")
                if not wrap_eth(w, amount_native, chain="ethereum"):
                    l("ETH->WETH wrap failed on Ethereum")
                    return False
            else:
                l(f"Insufficient WETH and ETH: have WETH={weth_bal:.6f}, ETH={native_bal:.6f}, need {amount_native:.6f}")
                return False
        amt_wei = int(amount_native * 1e18)
        if not ensure_allowance_ethereum(w, weth, ROUTER_ADDR["ethereum"], amt_wei):
            l("Ethereum WETH approval failed")
            return False
        resp = gw_client.uniswap_execute_swap(
            chain="ethereum",
            address=account.address,
            base=weth,
            quote=token_addr,
            amount=str(amt_wei),
            side="SELL",
            slippage=0.5,
            fee_tier=fee,
        )
        if resp.get("error"):
            l(f"Gateway swap error: {resp['error']}")
            return False
        l("Ethereum buy via Gateway successful")
        return True

    elif chain == "solana":
        addr = solana_wallet_address
        if not addr:
            l("Solana wallet address not configured")
            return False
        native_sol = get_native_balance("solana")
        if native_sol < amount_native:
            l(f"Insufficient SOL: have {native_sol:.6f}, need {amount_native:.6f}")
            return False

        # ── PRIORITY 1: Pump.fun ──────────────────────────────────
        l(f"[DEBUG] Checking pump.fun for {token_addr}...")
        pump_info = _is_pumpfun_token_solana(token_addr)
        l(f"[DEBUG] pump_info = {pump_info}")  # will be None on failure
        if pump_info:
            is_graduated = pump_info.get("graduated", False)
            venue = "pumpswap" if is_graduated else "pumpfun-bonding"
            l(f"Pump.fun token detected ({venue}): trying Pump.fun CLI first")
            pump_result = _execute_pumpfun_solana_buy(
                token_addr, "UNKNOWN", amount_native, addr, pump_info
            )
            if pump_result.get("success"):
                l(f"Solana buy via Pump.fun successful: {pump_result.get('output', '')}")
                return True
            else:
                l(f"Pump.fun failed ({pump_result.get('error', 'unknown')}): falling through to Jupiter")

        # ── PRIORITY 2: Jupiter Direct (API key) ───────────────────
        amount_lamports = int(amount_native * 1e9)
        l(f"Trying Jupiter Direct API for {amount_native:.4f} SOL...")
        direct_resp = jupiter_direct_swap(
            wallet_address=addr,
            base_token=SOLANA_WSOL,
            quote_token=token_addr,
            amount=float(amount_lamports),
            side="BUY",
            slippage_bps=100,
        )
        if not direct_resp.get("error"):
            l(f"Solana buy via Jupiter Direct: {direct_resp.get('txid', 'unknown')}")
            return True
        l(f"Jupiter Direct error: {direct_resp.get('error')}")

        # ── PRIORITY 3: Jupiter via Gateway ───────────────────────
        resp = gw_client.jupiter_execute_swap(
            wallet_address=addr,
            base_token=SOLANA_WSOL,
            quote_token=token_addr,
            amount=float(amount_lamports),
            side="BUY",
            slippage_pct=1.0,
        )
        if not resp.get("error"):
            l("Solana buy via Jupiter Gateway successful")
            unwrap_wsol()
            return True
        l(f"Jupiter Gateway error: {resp.get('error')}")

        # ── PRIORITY 4: Raydium CPMM ──────────────────────────────
        l("Falling back to Raydium CPMM...")
        raydium_ok, raydium_msg = _execute_raydium_solana_buy(token_addr, amount_native, addr)
        if raydium_ok:
            l(f"Solana buy via Raydium successful: {raydium_msg}")
            return True
        l(f"Raydium fallback failed: {raydium_msg}")

        l("All Solana venues exhausted; buy failed")
        return False
    return False


def execute_sell(
    chain: str, token_addr: str, token_amount: float, decimals: int
) -> bool:
    global account
    account = get_account(chain)
    amount_small = int(token_amount * (10**decimals))
    fee = POS.get("fee", FEE_DEFAULT)
    if chain == "base":
        w = gw()
        if not w:
            return False
        if not ensure_allowance_base(w, token_addr, ROUTER_ADDR["base"], amount_small):
            l("Base token approve failed for sell")
            return False
        if not swap_t2w(w, token_addr, amount_small, fee):
            return False
        # Unwrap all WETH → ETH after sell (wallet should hold only native ETH + token positions)
        weth_contract = w.eth.contract(
            address=WETH_ADDR["base"],
            abi=[{"inputs": [{"name": "amount", "type": "uint256"}], "name": "withdraw", "outputs": [], "stateMutability": "nonpayable", "type": "function"}],
        )
        weth_bal = weth_contract.functions.balanceOf(account.address).call()
        if weth_bal > 1000000000000:  # > 0.001 WETH threshold
            tx = weth_contract.functions.withdraw(weth_bal).build_transaction(
                {
                    "from": account.address,
                    "nonce": w.eth.get_transaction_count(account.address, "pending"),
                    "gas": 120000,
                    "maxFeePerGas": get_gas_price(w),
                    "maxPriorityFeePerGas": get_gas_price(w),
                }
            )
            signed = account.sign_transaction(tx)
            tx_hash = w.eth.send_raw_transaction(signed.raw_transaction)
            rc = w.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            if rc and rc.status == 1:
                l(f"Unwrapped {weth_bal/1e18:.6f} WETH → ETH post-sell")
            else:
                l(f"WETH unwrap FAILED after sell: {tx_hash.hex()}")
        return True
    elif chain == "ethereum":
        w = gw_eth()
        if not w:
            return False
        if not ensure_allowance_ethereum(
            w, token_addr, ROUTER_ADDR["ethereum"], amount_small
        ):
            l("Ethereum token approve failed for sell")
            return False
        resp = gw_client.uniswap_execute_swap(
            chain="ethereum",
            address=account.address,
            base=token_addr,
            quote=WETH_ADDR["ethereum"],
            amount=str(amount_small),
            side="SELL",
            slippage=0.5,
            fee_tier=fee,
        )
        if resp.get("error"):
            l(f"Gateway sell error: {resp['error']}")
            return False
        l("Ethereum sell via Gateway successful")
        # Unwrap all WETH → ETH after sell
        w_eth = gw_eth()
        if w_eth:
            weth_contract = w_eth.eth.contract(
                address=WETH_ADDR["ethereum"],
                abi=[{"inputs": [{"name": "amount", "type": "uint256"}], "name": "withdraw", "outputs": [], "stateMutability": "nonpayable", "type": "function"}],
            )
            weth_bal = weth_contract.functions.balanceOf(account.address).call()
            if weth_bal > 1000000000000:
                tx = weth_contract.functions.withdraw(weth_bal).build_transaction(
                    {
                        "from": account.address,
                        "nonce": w_eth.eth.get_transaction_count(account.address, "pending"),
                        "gas": 120000,
                        "maxFeePerGas": get_gas_price(w_eth),
                        "maxPriorityFeePerGas": get_gas_price(w_eth),
                    }
                )
                signed = account.sign_transaction(tx)
                tx_hash = w_eth.eth.send_raw_transaction(signed.raw_transaction)
                rc = w_eth.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
                if rc and rc.status == 1:
                    l(f"Unwrapped {weth_bal/1e18:.6f} WETH → ETH post-sell (Ethereum)")
                else:
                    l(f"WETH unwrap FAILED after sell: {tx_hash.hex()}")
        return True
    elif chain == "solana":
        addr = solana_wallet_address
        if not addr:
            l("Solana wallet address missing")
            return False

        # ── PRIORITY 1: Pump.fun / PumpSwap ────────────────────────
        pump_info = _is_pumpfun_token_solana(token_addr)
        if pump_info:
            pump_result = _execute_pumpfun_solana_sell(
                token_addr,
                symbol=POS.get("sym", "UNKNOWN"),
                wallet_addr=addr,
                pump_info=pump_info,
            )
            if pump_result.get("success"):
                l(f"Solana sell via Pump.fun: {pump_result.get('output', '')}")
                _unwrap_sol()
                return True
            l(f"Pump.fun sell failed ({pump_result.get('error', 'unknown')}): falling through to Jupiter")

        # ── PRIORITY 2: Jupiter Direct (API key) ───────────────────
        l("Trying Jupiter Direct for Solana sell...")
        direct_resp = jupiter_direct_swap(
            wallet_address=addr,
            base_token=token_addr,
            quote_token=SOLANA_WSOL,
            amount=float(amount_small),
            side="SELL",
            slippage_bps=100,
        )
        if not direct_resp.get("error"):
            l(f"Solana sell via Jupiter Direct: {direct_resp.get('txid', 'unknown')}")
            _unwrap_sol()
            return True
        l(f"Jupiter Direct sell error: {direct_resp.get('error')}")


def _unwrap_sol() -> None:
    """Close WSOL ATA to convert back to native SOL."""
    try:
        from solana_adapter import SolanaProgramAdapter as SolanaAdapter
        adapter = SolanaAdapter(
            rpc_url=os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
            private_key=os.environ.get("WALLET_PRIVATE_KEY_SOLANA", ""),
        )
        wsol_mint = "So11111111111111111111111111111111111111112"
        bal = adapter.get_token_balance(wsol_mint)
        if bal and bal > 1000:  # > 0.000001 SOL worth
            l(f"[SOL] Unwrapping {bal/1e9:.6f} WSOL → SOL...")
            tx = adapter.close_wsol_ata()
            if tx:
                l(f"[SOL] Unwrapped: {tx}")
            else:
                l("[SOL] Unwrap returned no txid")
        else:
            l("[SOL] No WSOL to unwrap")
    except Exception as e:
        l(f"[SOL] Unwrap error: {e}")


# ==================== RAYDIUM ====================



        # ── PRIORITY 2: Jupiter via Gateway ───────────────────────
        resp = gw_client.jupiter_execute_swap(
            wallet_address=addr,
            base_token=token_addr,
            quote_token=SOLANA_WSOL,
            amount=float(amount_small),
            side="SELL",
            slippage_pct=1.0,
        )
        if resp.get("error"):
            l(f"Jupiter Gateway sell error: {resp['error']}")
        else:
            l("Solana sell via Jupiter Gateway successful")
            _unwrap_sol()
            return True

        # ── PRIORITY 3: Raydium CPMM ──────────────────────────────
        l("Falling back to Raydium CPMM for sell...")
        raydium_ok, raydium_msg = _execute_raydium_solana_sell(token_addr, token_amount, addr, decimals)
        if raydium_ok:
            l(f"Solana sell via Raydium: {raydium_msg}")
            _unwrap_sol()
            return True
        l(f"Raydium sell fallback failed: {raydium_msg}")

        l("All Solana sell venues exhausted")
        return False
    return False


def _manage_positions():
    """Check stop-loss and take-profit on open positions."""


# ==================== STATE & SURVIVAL ====================
POS = {
    "on": False,
    "sym": None,
    "tok_addr": None,
    "chain": None,
    "t0": 0,
    "entry_px": 0,
    "entry_eth": 0,
    "used_weth": False,
    "decimals": 18,
    "fee": FEE_DEFAULT,
}


def us(act="", det=""):
    try:
        with open(SF) as f:
            s = json.load(f)
        s["last_check"] = time.time()
        s["last_action"] = act
        s["last_action_details"] = det
        with open(SF, "w") as f:
            json.dump(s, f, indent=2)
    except:
        pass


def pr() -> bool:
    if not os.path.exists(SF):
        return True
    with open(SF) as f:
        s = json.load(f)
    last_timestamp = s.get("last_rent_payment_timestamp")
    if last_timestamp is None:
        last_timestamp = 0
    if (time.time() - last_timestamp) > 3300:
        l("!!! RENT DUE !!!")
        r = subprocess.run(["python3", RS], capture_output=True, text=True, timeout=120)
        if "SUCCESS!" in r.stdout or "Hourly rent paid this cycle: YES" in r.stdout:
            l("Rent PAID")
            us("RENT_PAID")
            tg_notify("✅ Rent paid for this cycle")
            return False
        else:
            l("Rent FAIL")
            tg_notify("⚠️ Rent payment FAILED")
            return True
    return False


# Gas reserves per chain (in native units)
GAS_RESERVE = {"base": 0.00005, "ethereum": 0.001, "solana": 0.01}

# Circuit-breaker guard for repeated execution failures
BUY_FAIL_GUARD = {
    "count": 0,
    "cooldown_until": 0.0,
}


# ==================== MAIN LOOP ====================
def main():
    global account
    if not acquire_singleton_lock():
        return
    l("=" * 60)
    l("SURVIVAL v23 - MULTICHAIN TRADING")
    l("=" * 60)
    l(f"Wallet Base: {account_base.address}")
    l(f"Wallet Ethereum: {account_ethereum.address}")
    if solana_wallet_address:
        l(f"Wallet Solana: {solana_wallet_address}")
    else:
        l("Wallet Solana: <not set>")
    l(f"Gas reserve (Base/ETH/SOL): {GAS_RESERVE}")
    if not tg_enabled:
        l("Telegram: disabled (TELEGRAM_CHAT_ID missing)")
    l("=" * 60)

    w_test = gw()
    if not w_test:
        l("Cannot connect to Base RPC - exit")
        return

    try:
        tg_notify(
            f"🚀 SURVIVAL Bot started\nBase: {account_base.address[:10]}...\nEthereum: {account_ethereum.address[:10]}..."
        )
    except:
        pass

    px_eth = ep()
    cyc = 0

    while True:
        try:
            cyc += 1
            l(f"--- CYCLE {cyc} ---")
            # DISABLED FOR TRAINING:             pr()
            px_eth = ep()

            # Fetch signals
            l("Fetching signals...")
            try:
                # Threading-based timeout: SIGALRM doesn't reliably interrupt
                # requests calls; use Event.wait() with a watchdog thread instead.
                import threading

                result_holder = [None]  # nonlocal container
                done_event = threading.Event()

                def _fetch():
                    result_holder[0] = aggregate_signals()
                    done_event.set()

                t = threading.Thread(target=_fetch, daemon=True)
                t.start()
                if not done_event.wait(55):
                    l("SIGNALS: timeout after 55s — continuing without new signals")
                    sigs = result_holder[0] or []
                else:
                    sigs = result_holder[0] or []
                l(f"Got {len(sigs)} signals")
                if sigs:
                    top = sigs[0]
                    conf_val = float(top.get("confidence") or 0.0)
                    tg_notify(
                        f"📊 Signals: {len(sigs)} found\nTop: {top.get('token','?')} (conf={conf_val:.2f})\nAction: {top.get('action','?')}\nChain: {top.get('chain','base')}"
                    )
                else:
                    top = None
            except Exception as e:
                l(f"Signal error: {e}")
                tg_notify(f"⚠️ Signal error: {e}")
                sigs = []
                top = None

            # Handle open position
            if POS["on"]:
                chain = POS["chain"]
                tok_addr = POS["tok_addr"]
                decimals = POS.get("decimals", 18)
                try:
                    r = requests.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{tok_addr}",
                        timeout=8,
                    )
                    if r.status_code == 200 and r.json().get("pairs"):
                        p = r.json()["pairs"][0]
                        price_usd = p.get("priceUsd")
                        if price_usd is None:
                            l(f"No price data for {tok_addr}")
                            time.sleep(300)
                            continue
                        curr_px = float(price_usd)
                        if curr_px > 0:
                            entry_px = POS["entry_px"]
                            if entry_px is None or entry_px == 0:
                                l(f"Invalid entry price: {entry_px}")
                                time.sleep(300)
                                continue
                            chg = (curr_px - entry_px) / entry_px * 100
                            l(
                                f"POS: {POS['sym']} on {chain} entry ${POS['entry_px']:.8f} now ${curr_px:.8f} ({chg:+.2f}%)"
                            )
                            if chg >= 8:
                                l(">>> PROFIT TARGET - SELL")
                                token_bal = get_token_balance(chain, tok_addr, decimals)
                                if token_bal > 0:
                                    if execute_sell(
                                        chain, tok_addr, token_bal, decimals
                                    ):
                                        POS["on"] = False
                                        us("PROFIT", f"{chg:.1f}%")
                                        l("Position closed, native retained")
                                        tg_notify(
                                            f"✅ PROFIT SELL\n{POS['sym']} +{chg:.1f}%\nChain: {chain}"
                                        )
                                    else:
                                        l("Sell FAIL")
                                        tg_notify(
                                            f"❌ SELL FAIL (profit): {POS['sym']}"
                                        )
                                else:
                                    l("No token balance to sell")
                                    POS["on"] = False
                            elif (time.time() - POS["t0"]) / 60 > 10:
                                l(">>> TIME STOP - SELL")
                                token_bal = get_token_balance(chain, tok_addr, decimals)
                                if token_bal > 0:
                                    if execute_sell(
                                        chain, tok_addr, token_bal, decimals
                                    ):
                                        POS["on"] = False
                                        us("TIME_STOP")
                                        l("Position closed (time stop)")
                                        tg_notify(
                                            f"⏰ TIME STOP SELL\n{POS['sym']} after 10m\nChain: {chain}"
                                        )
                                    else:
                                        l("Sell FAIL")
                                        tg_notify(f"❌ SELL FAIL (time): {POS['sym']}")
                                else:
                                    l("No token balance; clearing position")
                                    POS["on"] = False
                except Exception as e:
                    l(f"Position check error: {e}")
                time.sleep(300)
                continue

            if not top:
                l("No signals - waiting")
                time.sleep(300)
                continue

            token_sym = top.get("token")
            if not token_sym:
                l("Top signal missing token; skipping")
                time.sleep(60)
                continue
            action = str(top.get("action", "BUY")).upper()
            chain = top.get("chain", "base")
            account = get_account(chain)

            # Resolve token address
            token_addr = top.get("token_address")
            if not token_addr:
                token_addr = resolve_token(token_sym, chain)
            if not token_addr:
                l(f"Cannot resolve token {token_sym} on {chain}")
                time.sleep(300)
                continue

            # Fetch metadata
            meta = fetch_token_metadata(token_addr, chain)
            if (
                not meta
                or meta.get("price_usd") is None
                or float(meta.get("price_usd", 0)) == 0
            ):
                l(f"No metadata for {token_addr} on {chain}")
                time.sleep(300)
                continue
            decimals = meta["decimals"]
            fee = meta.get("fee", FEE_DEFAULT)

            # Compute capital on this chain
            native_bal = get_native_balance(chain)
            wrapped_addr = (
                WETH_ADDR.get(chain) if chain in ("base", "ethereum") else SOLANA_WSOL
            )
            wrapped_decimals = (
                NATIVE_DECIMALS.get(chain, 18) if chain in ("base", "ethereum") else 9
            )
            wrapped_bal = get_token_balance(chain, wrapped_addr, wrapped_decimals)
            total_capital = native_bal + wrapped_bal
            l(
                f"Chain {chain} capital: Native {native_bal:.6f}, Wrapped {wrapped_bal:.6f} = {total_capital:.6f} native units"
            )

            gas_reserve = GAS_RESERVE.get(chain, MG)
            tradable = max(0.0, total_capital - gas_reserve)
            if tradable <= 0:
                l(f"Insufficient tradable capital on {chain} (need > {gas_reserve})")
                time.sleep(60)
                continue

            if action != "BUY":
                l(f"Signal action {action} not BUY; ignoring")
                time.sleep(300)
                continue

            if BUY_FAIL_GUARD["cooldown_until"] > time.time():
                secs = int(BUY_FAIL_GUARD["cooldown_until"] - time.time())
                l(f"Buy cooldown active after repeated failures ({secs}s remaining)")
                time.sleep(min(60, max(5, secs)))
                continue

            use_amt = tradable * 0.98
            l(
                f"EXECUTE BUY: {token_sym} addr={token_addr} chain={chain} amount={use_amt:.6f} native fee={fee}"
            )
            success = execute_buy(chain, token_addr, use_amt, meta)
            if success:
                BUY_FAIL_GUARD["count"] = 0
                BUY_FAIL_GUARD["cooldown_until"] = 0.0
                POS.update(
                    {
                        "on": True,
                        "sym": token_sym,
                        "tok_addr": token_addr,
                        "chain": chain,
                        "t0": time.time(),
                        "entry_px": float(meta["price_usd"]),
                        "entry_eth": use_amt,
                        "used_weth": wrapped_bal >= use_amt,
                        "decimals": decimals,
                        "fee": fee,
                    }
                )
                us("BUY", f"{token_sym} on {chain}")
                tg_notify(
                    f"🟢 BOUGHT {token_sym}\nChain: {chain}\nAmt: {use_amt:.6f} native\nPrice: ${float(meta['price_usd']):.8f}\nFee: {fee}"
                )
            else:
                BUY_FAIL_GUARD["count"] += 1
                if BUY_FAIL_GUARD["count"] >= 3:
                    BUY_FAIL_GUARD["cooldown_until"] = time.time() + 900
                    l("BUY FAILED x3 -> entering 15m cooldown")
                else:
                    l("BUY FAILED")
                tg_notify(
                    f"🔴 BUY FAILED: {token_sym} on {chain} (fee={fee}, fail_count={BUY_FAIL_GUARD['count']})"
                )

            # Runway estimate: total_capital * eth_price / 0.50 per hour
            eth_price = px_eth
            runway_hrs = (total_capital * eth_price) / 0.50 if eth_price else 0
            l(f"Runway: {runway_hrs:.1f}h (if price static)")
            time.sleep(300)

        except KeyboardInterrupt:
            l("STOP")
            break
        except Exception as e:
            l(f"FATAL CYCLE ERROR: {e}")
            tg_notify(f"💥 FATAL ERROR: {e}")
            time.sleep(60)

    if tg:
        try:
            tg.stop()
        except:
            pass


if __name__ == "__main__":
    main()
