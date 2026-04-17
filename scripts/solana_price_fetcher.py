#!/usr/bin/env python3
"""
Solana On-Chain Price Fetcher v2
Fetches SOL/USDC prices from 30+ Solana DEX pools via on-chain reads and APIs.
For arbitrage: compares prices across all sources to find spreads.
"""
import struct
import base64
import requests
import json
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@dataclass
class PriceQuote:
    dex: str
    pool: str
    price: float
    source: str
    tvl: float = 0.0
    volume_24h: float = 0.0
    timestamp: float = 0.0


class SolanaRPC:
    def __init__(self, url: str = SOLANA_RPC):
        self.url = url
        self.s = requests.Session()

    def get_account(self, addr: str) -> Optional[bytes]:
        r = self.s.post(
            self.url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [addr, {"encoding": "base64"}],
            },
            timeout=10,
        )
        v = r.json().get("result", {}).get("value")
        if v and v.get("data"):
            return base64.b64decode(v["data"][0])
        return None

    def get_balance(self, addr: str) -> Tuple[int, int]:
        r = self.s.post(
            self.url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountBalance",
                "params": [addr],
            },
            timeout=10,
        )
        v = r.json().get("result", {}).get("value", {})
        return int(v.get("amount", "0")), int(v.get("decimals", 0))


def base58(data: bytes) -> str:
    B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = int.from_bytes(data, "big")
    enc = ""
    while num > 0:
        num, r = divmod(num, 58)
        enc = B58[r] + enc
    for b in data:
        if b == 0:
            enc = "1" + enc
        else:
            break
    return enc


# ═══════════════════════════════════════════════════════════════
# READERS: on-chain price extraction by DEX type
# ═══════════════════════════════════════════════════════════════


def read_sqrt_price(rpc: SolanaRPC, addr: str, offset_hint: int = 0) -> Optional[float]:
    """Read sqrt_price_x64 from a CLMM/Whirlpool account and compute price."""
    data = rpc.get_account(addr)
    if not data:
        return None

    # If we know the offset, use it directly
    if offset_hint > 0 and len(data) >= offset_hint + 16:
        sqrt = int.from_bytes(data[offset_hint : offset_hint + 16], "little")
        if sqrt > 0:
            raw = (sqrt / (2**64)) ** 2
            price = raw * 10**3  # SOL=9, USDC=6 => 10^(9-6)
            if 50 < price < 200:
                return price

    # Scan for the right offset
    for off in range(40, min(len(data) - 16, 350)):
        val = int.from_bytes(data[off : off + 16], "little")
        if val > 0:
            raw = (val / (2**64)) ** 2
            price = raw * 10**3
            if 50 < price < 200:
                return price
    return None


def read_amm_vaults(rpc: SolanaRPC, addr: str) -> Optional[float]:
    """Read vault balances from an AMM pool account."""
    data = rpc.get_account(addr)
    if not data or len(data) < 104:
        return None

    # Try common vault offsets
    for base_offset in [40, 72, 8, 128]:
        try:
            va = base58(data[base_offset : base_offset + 32])
            vb = base58(data[base_offset + 32 : base_offset + 64])
            amt_a, dec_a = rpc.get_balance(va)
            amt_b, dec_b = rpc.get_balance(vb)
            if amt_a > 0 and dec_a in (6, 8, 9) and dec_b in (6, 8, 9):
                price = (amt_b / 10**dec_b) / (amt_a / 10**dec_a)
                if 50 < price < 200:
                    return price
        except Exception:
            continue
    return None


def read_serum_vaults(rpc: SolanaRPC, addr: str) -> Optional[float]:
    """Read vault balances from a Serum/Openbook market."""
    data = rpc.get_account(addr)
    if not data or len(data) < 270:
        return None
    try:
        coin_vault = base58(data[112:144])
        pc_vault = base58(data[144:176])
        amt_c, dec_c = rpc.get_balance(coin_vault)
        amt_p, dec_p = rpc.get_balance(pc_vault)
        if amt_c > 0:
            return (amt_p / 10**dec_p) / (amt_c / 10**dec_c)
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# API-BASED READERS
# ═══════════════════════════════════════════════════════════════


def fetch_raydium_api() -> List[PriceQuote]:
    """Fetch all SOL/USDC pools from Raydium API."""
    results = []
    try:
        resp = requests.get(
            "https://api-v3.raydium.io/pools/info/mint",
            params={
                "mint1": SOL,
                "mint2": USDC,
                "poolType": "all",
                "poolSortField": "liquidity",
                "sortType": "desc",
                "page": 1,
                "pageSize": 50,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            for p in resp.json().get("data", {}).get("data", []):
                price = p.get("price", 0)
                pool_id = p.get("id", "")
                pool_type = p.get("type", "?")
                tvl = p.get("tvl", 0) or 0
                vol = p.get("day", {}).get("volume", 0) or 0
                if price and 50 < price < 200:
                    results.append(
                        PriceQuote(
                            dex=f"raydium_{pool_type.lower()}",
                            pool=pool_id,
                            price=price,
                            source="api",
                            tvl=tvl,
                            volume_24h=vol,
                            timestamp=time.time(),
                        )
                    )
    except Exception:
        pass
    return results


def fetch_orca_api() -> List[PriceQuote]:
    """Fetch all SOL/USDC pools from Orca API."""
    results = []
    try:
        resp = requests.get("https://api.orca.so/v1/whirlpool/list", timeout=15)
        pools = resp.json().get("whirlpools", [])
        for p in pools:
            ta = p.get("tokenA", {})
            tb = p.get("tokenB", {})
            ma = ta.get("mint", "") if isinstance(ta, dict) else ""
            mb = tb.get("mint", "") if isinstance(tb, dict) else ""
            if (SOL in [ma, mb]) and (USDC in [ma, mb]):
                addr = p.get("address", "")
                tvl = p.get("tvl", 0)
                if isinstance(tvl, dict):
                    tvl = tvl.get("value", 0)
                vol = p.get("volume", {})
                vol_day = vol.get("day", 0) if isinstance(vol, dict) else 0

                # Read on-chain price (API price is stale)
                on_chain_price = None
                try:
                    on_chain_price = read_sqrt_price(SolanaRPC(), addr, offset_hint=65)
                except Exception:
                    pass

                if on_chain_price and 50 < on_chain_price < 200:
                    results.append(
                        PriceQuote(
                            dex="orca_whirlpool",
                            pool=addr,
                            price=on_chain_price,
                            source="on_chain",
                            tvl=float(tvl),
                            volume_24h=(
                                float(vol_day)
                                if isinstance(vol_day, (int, float))
                                else 0
                            ),
                            timestamp=time.time(),
                        )
                    )
    except Exception:
        pass
    return results


def fetch_jupiter_quote() -> Optional[PriceQuote]:
    """Get real-time quote from Jupiter API."""
    try:
        resp = requests.get(
            "https://quote-api.jup.ag/v6/quote",
            params={
                "inputMint": SOL,
                "outputMint": USDC,
                "amount": "1000000000",
                "slippageBps": "50",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            out = int(data.get("outAmount", "0"))
            if out > 0:
                return PriceQuote(
                    dex="jupiter",
                    pool="aggregator",
                    price=out / 1e6,
                    source="api",
                    timestamp=time.time(),
                )
    except Exception:
        pass
    return None


def fetch_raydium_quote() -> Optional[PriceQuote]:
    """Get real-time quote from Raydium API."""
    try:
        resp = requests.get(
            "https://transaction-v1.raydium.io/compute/swap-base-in",
            params={
                "inputMint": SOL,
                "outputMint": USDC,
                "amount": "1000000000",
                "slippageBps": "50",
                "txVersion": "V0",
            },
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("success"):
            out = int(resp.json()["data"].get("outputAmount", "0"))
            if out > 0:
                return PriceQuote(
                    dex="raydium_quote",
                    pool="api",
                    price=out / 1e6,
                    source="api",
                    timestamp=time.time(),
                )
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# ON-CHAIN POOL REGISTRY
# ═══════════════════════════════════════════════════════════════

# Verified on-chain pools with known sqrt_price offsets
ONCHAIN_POOLS = {
    # Orca Whirlpool: sqrt_price at offset 65 (after 8-byte discriminator)
    "orca_wp_1": ("Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE", "orca_whirlpool", 65),
    "orca_wp_2": ("FpCMFDFGYotvufJ7HrFHsWEiiQCGbkLCtwHiDnh7o28Q", "orca_whirlpool", 65),
    "orca_wp_3": ("7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm", "orca_whirlpool", 65),
    "orca_wp_4": ("HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ", "orca_whirlpool", 65),
    "orca_wp_5": ("21gTfxAnhUDjJGZJDkTXctGFKT8TeiXx6pN1CEg9K1uW", "orca_whirlpool", 65),
    "orca_wp_6": ("83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6d", "orca_whirlpool", 65),
    "orca_wp_7": ("DFVTutNYXD8z4T5cRdgpso1G3sZqQvMHWpW2N99E4DvE", "orca_whirlpool", 65),
    "orca_wp_8": ("6d4UYGAEs4Akq6py8Vb3Qv5PvMkecPLS1Z9bBCcip2R7", "orca_whirlpool", 65),
    # Raydium CLMM: sqrt_price at offset 253
    "raydium_clmm_1": (
        "3ucNos4NbumPLZNWztqGHNFFgkHeRMBQAVemeeomsUxv",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_2": (
        "CYbD9RaToYMtWKA7QZyoLahnHdWq553Vm62Lh6qWtuxq",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_3": (
        "8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_4": (
        "2QdhepnKRTLjjSqPL1PtKNwqrUkoLee5Gqs8bvZhRdMv",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_5": (
        "GqxUEcFw8GbfDPoWU6UG2ypvsM3aw3vZmiN4e1Nbv94G",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_6": (
        "5s7njN2X6k3trkibTKX6LJFu4PnybYhCuADP9LD2fhuP",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_7": (
        "CztrCcLhgfazkBchMW7wXQL37AWQdBP1tQWHBR249neh",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_8": (
        "6MUjnGffYaqcHeqv4nNemUQVNMpJab3W2NV9bfPj576c",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_9": (
        "2SjLv6XwViJ17rq21N1y98LbMee1J4DXinP61rk9v2aK",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_10": (
        "7PLpcezEnTV2xXU6eL3j4kLi9MJJFUngsWQvUNKyjE2V",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_11": (
        "EXHyQxMSttcvLPwjENnXCPZ8GmLjJYHtNBnAkcFeFKMn",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_12": (
        "CiSQxEhiS1j7PVHy57LqmjFWL1N7ciYD45Enq5tSyfaN",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_13": (
        "2JtkunkYCRbe5YZuGU6kLFmNwN22Ba1pCicHoqW5Eqja",
        "raydium_clmm",
        253,
    ),
    "raydium_clmm_14": (
        "7byw3sD4hNG5NTwTHFRfxyASJCHfed4i6FKVdtqXGtru",
        "raydium_clmm",
        253,
    ),
}


def fetch_onchain_pools() -> List[PriceQuote]:
    """Fetch prices from all on-chain pool accounts."""
    rpc = SolanaRPC()
    results = []

    def read_one(name, addr, dex, offset):
        price = read_sqrt_price(rpc, addr, offset_hint=offset)
        if price and 50 < price < 200:
            return PriceQuote(
                dex=dex,
                pool=addr,
                price=price,
                source="on_chain",
                timestamp=time.time(),
            )
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(read_one, name, addr, dex, offset): name
            for name, (addr, dex, offset) in ONCHAIN_POOLS.items()
        }
        for f in as_completed(futures):
            q = f.result()
            if q:
                results.append(q)

    return results


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════


def fetch_all() -> List[PriceQuote]:
    """Fetch prices from all sources in parallel."""
    all_quotes = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(fetch_raydium_api),
            pool.submit(fetch_orca_api),
            pool.submit(fetch_onchain_pools),
            pool.submit(fetch_jupiter_quote),
            pool.submit(fetch_raydium_quote),
        ]
        for f in futures:
            try:
                result = f.result(timeout=30)
                if isinstance(result, list):
                    all_quotes.extend(result)
                elif result:
                    all_quotes.append(result)
            except Exception:
                pass

    return all_quotes


def find_arbitrage(quotes: List[PriceQuote]) -> List[dict]:
    """Find arbitrage opportunities."""
    if len(quotes) < 2:
        return []

    opps = []
    for i in range(len(quotes)):
        for j in range(i + 1, len(quotes)):
            q1, q2 = quotes[i], quotes[j]
            spread = abs(q1.price - q2.price)
            mn = min(q1.price, q2.price)
            if mn > 0:
                pct = (spread / mn) * 100
                if pct > 0.05:
                    buy = q1 if q1.price < q2.price else q2
                    sell = q2 if q1.price < q2.price else q1
                    opps.append(
                        {
                            "buy": buy.dex,
                            "sell": sell.dex,
                            "buy_price": buy.price,
                            "sell_price": sell.price,
                            "spread_pct": pct,
                            "spread_usd": spread,
                            "buy_pool": buy.pool[:20],
                            "sell_pool": sell.pool[:20],
                        }
                    )
    return sorted(opps, key=lambda x: x["spread_pct"], reverse=True)


if __name__ == "__main__":
    print("=" * 90)
    print("SOLANA DEX PRICE FETCHER v2 — 30+ POOLS")
    print("=" * 90)

    quotes = fetch_all()
    quotes.sort(key=lambda q: q.price)

    print(
        f"\n{'DEX':<25} | {'Price':>12} | {'TVL':>14} | {'Vol 24h':>14} | {'Source':<10}"
    )
    print("-" * 85)

    for q in quotes:
        tvl = f"${q.tvl:,.0f}" if q.tvl > 0 else ""
        vol = f"${q.volume_24h:,.0f}" if q.volume_24h > 0 else ""
        print(
            f"{q.dex:<25} | ${q.price:>11.4f} | {tvl:>14} | {vol:>14} | {q.source:<10}"
        )

    print(f"\n{'='*85}")
    print(f"Total pools: {len(quotes)}")

    if quotes:
        prices = [q.price for q in quotes]
        print(f"Price range: ${min(prices):.4f} — ${max(prices):.4f}")
        print(f"Spread: {((max(prices)-min(prices))/min(prices))*100:.3f}%")

    print(f"\n{'='*85}")
    print("ARBITRAGE OPPORTUNITIES (>0.05%)")
    print("=" * 85)

    arbs = find_arbitrage(quotes)
    if arbs:
        for a in arbs[:10]:
            print(
                f"  Buy {a['buy']:<22} @ ${a['buy_price']:.4f} -> "
                f"Sell {a['sell']:<22} @ ${a['sell_price']:.4f} "
                f"= {a['spread_pct']:.3f}% (${a['spread_usd']:.4f})"
            )
    else:
        print("  No significant arbitrage opportunities found.")
