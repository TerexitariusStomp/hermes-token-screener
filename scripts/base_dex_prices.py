#!/usr/bin/env python3
"""
BASE DEX PRICE MONITOR v7 — Comprehensive DEX integration
Uses Dexscreener API for all DEXes + on-chain for major ones
"""

import json
import urllib.request
import ssl
import time
import os
import sqlite3
import urllib.parse

RPCS = ["https://base.llamarpc.com", "https://base.drpc.org"]
rpc_idx = 0

def call(method, params=[]):
    global rpc_idx
    for _ in range(4):
        try:
            url = RPCS[rpc_idx % len(RPCS)]
            payload = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=12, context=ssl.create_default_context()) as resp:
                return json.loads(resp.read().decode())
        except:
            rpc_idx += 1
            time.sleep(0.3)
    return {"error": "all failed"}

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
DAI = "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb"
AERO = "0x940181a94A35A4569D4521129DfD34b47d5Ed16c"
USDbC = "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA"
cbBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
crvUSD = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"

DECIMALS = {WETH: 18, USDC: 6, DAI: 18, AERO: 18, USDbC: 6, cbBTC: 8, crvUSD: 18}

def get_dexscreener_prices():
    """Get all WETH prices from Dexscreener."""
    prices = {}
    try:
        url = "https://api.dexscreener.com/latest/dex/tokens/" + WETH
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as resp:
            data = json.loads(resp.read().decode())
            for pair in data.get("pairs", []):
                dex = pair.get("dexId", "?")
                price = float(pair.get("priceUsd", 0))
                quote = pair.get("quoteToken", {}).get("symbol", "?")
                base = pair.get("baseToken", {}).get("symbol", "?")
                liq = float(pair.get("liquidity", {}).get("usd", 0))
                vol = float(pair.get("volume", {}).get("h24", 0))
                pair_address = pair.get("pairAddress", "?")
                
                if price > 0 and base in ["WETH", "ETH"] and quote in ["USDC", "USDbC", "DAI", "USDT", "crvUSD"]:
                    prices[dex] = {
                        "price": price,
                        "pair": f"{base}/{quote}",
                        "liquidity": liq,
                        "volume_24h": vol,
                        "pair_address": pair_address,
                    }
    except Exception as e:
        print(f"  Dexscreener error: {e}")
    return prices

def get_v2_price(factory, tA, tB):
    """Get price from V2 factory."""
    data = "0xe6a43905" + tA[2:].zfill(64) + tB[2:].zfill(64)
    r = call("eth_call", [{"to": factory, "data": data}, "latest"])
    pool = "0x" + r.get("result", "0x")[26:66]
    if pool == "0x" + "0"*40:
        return None
    r2 = call("eth_call", [{"to": pool, "data": "0x0902f1ac"}, "latest"])
    result = r2.get("result", "")
    if not result or len(result) < 194:
        return None
    r0, r1 = int(result[:66], 16), int(result[66:130], 16)
    if r0 > 0 and r1 > 0:
        dec0 = DECIMALS.get(tA, 18)
        dec1 = DECIMALS.get(tB, 18)
        if tA == WETH and tB in [USDC, DAI, USDbC, crvUSD]:
            price = (r1 / 10**dec1) / (r0 / 10**dec0)
        elif tA in [USDC, DAI, USDbC, crvUSD] and tB == WETH:
            price = (r0 / 10**dec0) / (r1 / 10**dec1)
        else:
            return None
        return {"pool": pool, "price": price, "pair": f"WETH/{tB}"}
    return None

def get_v3_price(factory, tA, tB):
    """Get price from V3 factory."""
    for fee in [100, 500, 3000, 10000]:
        data = "0x1698ee82" + tA[2:].zfill(64) + tB[2:].zfill(64) + hex(fee)[2:].zfill(64)
        r = call("eth_call", [{"to": factory, "data": data}, "latest"])
        pool = "0x" + r.get("result", "0x")[26:66]
        if pool == "0x" + "0"*40:
            continue
        r2 = call("eth_call", [{"to": pool, "data": "0x3850c7bd"}, "latest"])
        result = r2.get("result", "")
        if not result or len(result) < 66:
            continue
        sqrt = int(result[:66], 16)
        if sqrt > 0:
            raw = (sqrt / (2**96)) ** 2
            decA = DECIMALS.get(tA, 18)
            decB = DECIMALS.get(tB, 18)
            if tA == WETH and tB in [USDC, DAI, USDbC, crvUSD]:
                price = raw * (10 ** (decA - decB))
            elif tA in [USDC, DAI, USDbC, crvUSD] and tB == WETH:
                price = (10 ** (decB - decA)) / raw
            else:
                continue
            return {"pool": pool, "price": price, "fee_bps": fee, "pair": f"WETH/{tB}"}
    return None

# ─── ALL DEX CONTRACTS ──────────────────────────────────────

ALL_DEXES = {
    # V2 DEXes with known factories
    "Uniswap V2": {"type": "v2", "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"},
    "BaseSwap": {"type": "v2", "factory": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB"},
    "PancakeSwap": {"type": "v2", "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"},
    "SushiSwap": {"type": "v2", "factory": "0xc35DADB65012eC5796536bD9864eD8773aBc74C4"},
    "AlienBase": {"type": "v2", "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"},
    "Aerodrome": {"type": "v2", "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"},
    
    # V3 DEXes with known factories
    "Uniswap V3": {"type": "v3", "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"},
    "SushiSwap V3": {"type": "v3", "factory": "0xc35DADB65012eC5796536bD9864eD8773aBc74C4"},
    "PancakeSwap V3": {"type": "v3", "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"},
    
    # DEXes without known factories (use Dexscreener)
    "SynthSwap": {"type": "dexscreener"},
    "DackieSwap": {"type": "dexscreener"},
    "Omni Exchange": {"type": "dexscreener"},
    "Moonwell": {"type": "dexscreener"},
    "RocketSwap": {"type": "dexscreener"},
    "Smoothy": {"type": "dexscreener"},
    "Velodrome": {"type": "dexscreener"},
    "Wigoswap": {"type": "dexscreener"},
    "SaitaSwap": {"type": "dexscreener"},
    "EddyFinance": {"type": "dexscreener"},
    "Fenix Finance": {"type": "dexscreener"},
    "LeetSwap": {"type": "dexscreener"},
    "SoSwap": {"type": "dexscreener"},
    "SharkSwap": {"type": "dexscreener"},
    "BasePaintSwap": {"type": "dexscreener"},
    "Unicly": {"type": "dexscreener"},
    "Zebra Finance": {"type": "dexscreener"},
    "Hydrex": {"type": "dexscreener"},
    "QuickSwap": {"type": "dexscreener"},
    "IziSwap": {"type": "dexscreener"},
    
    # Aggregators
    "1inch V6": {"type": "dexscreener"},
    "Odos V2": {"type": "dexscreener"},
    "CoW Protocol": {"type": "dexscreener"},
    "ParaSwap V6": {"type": "dexscreener"},
    "0x Exchange": {"type": "dexscreener"},
    "KyberSwap": {"type": "dexscreener"},
    
    # Balancer
    "Balancer V2": {"type": "dexscreener"},
    
    # Curve
    "Curve": {"type": "dexscreener"},
    
    # Uniswap V4
    "Uniswap V4": {"type": "dexscreener"},
}

# ─── EXECUTE ────────────────────────────────────────────────

print("=" * 70)
print("  BASE DEX PRICE MONITOR v7 — Comprehensive DEX integration")
print("=" * 70)

results = []
failed_dexes = []

# 1. Get Dexscreener prices
print("\n[1] Fetching Dexscreener prices...")
print("-" * 70)
dexscreener_prices = get_dexscreener_prices()
print(f"  Found {len(dexscreener_prices)} DEX prices")
for dex, info in sorted(dexscreener_prices.items()):
    print(f"  {dex:<20} {info['price']:>12,.2f} USDC/ETH  {info['pair']:<10} liq=${info['liquidity']:,.0f}")

# 2. Scan all DEXes
print(f"\n[2] Scanning all DEXes...")
print("-" * 70)

for dex_name, config in ALL_DEXES.items():
    dtype = config["type"]
    factory = config.get("factory")
    info = None
    
    if dtype == "v2" and factory:
        # Try WETH/USDC
        info = get_v2_price(factory, WETH, USDC)
        if not info:
            # Try WETH/DAI
            info = get_v2_price(factory, WETH, DAI)
        if not info:
            # Try WETH/AERO
            info = get_v2_price(factory, WETH, AERO)
    
    elif dtype == "v3" and factory:
        # Try WETH/USDC
        info = get_v3_price(factory, WETH, USDC)
        if not info:
            # Try WETH/DAI
            info = get_v3_price(factory, WETH, DAI)
    
    if info and 100 < info["price"] < 10000:  # Sanity check
        results.append({
            "dex": dex_name,
            "price": info["price"],
            "method": f"{dtype.upper()} on-chain",
            "pool": info.get("pool"),
            "fee_bps": info.get("fee_bps"),
            "pair": info.get("pair", ""),
        })
        print(f"  ✓ {dex_name:<20} {info['price']:>12,.2f} USDC/ETH  [{dtype.upper()} on-chain]")
    else:
        # Dexscreener fallback
        dex_key = dex_name.lower().replace(" v2", "").replace(" v3", "").replace(" v6", "")
        if dex_key in dexscreener_prices:
            ds = dexscreener_prices[dex_key]
            results.append({
                "dex": dex_name,
                "price": ds["price"],
                "method": "Dexscreener API",
                "pair": ds["pair"],
                "liquidity": ds["liquidity"],
            })
            print(f"  ✓ {dex_name:<20} {ds['price']:>12,.2f} USDC/ETH  [Dexscreener]")
        else:
            failed_dexes.append(dex_name)
            print(f"  ✗ {dex_name:<20} no pool found")
    time.sleep(0.15)

# 3. Chainlink oracle
print(f"\n[3] Chainlink oracle...")
print("-" * 70)
ETH_USD_ORACLE = "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70"
USDC_USD_ORACLE = "0x7e860098F58bBFC8648a4311b374B1D669a2bc6B"
oracle = {}
for name, addr in [("ETH/USD", ETH_USD_ORACLE), ("USDC/USD", USDC_USD_ORACLE)]:
    r = call("eth_call", [{"to": addr, "data": "0x50d25bcd"}, "latest"])
    result = r.get("result", "")
    if result and len(result) >= 66:
        oracle[name] = int(result[:66], 16) / 1e8
        print(f"  Chainlink {name}: {oracle[name]:,.4f}")

if "ETH/USD" in oracle and "USDC/USD" in oracle:
    implied = oracle["ETH/USD"] / oracle["USDC/USD"]
    results.append({"dex": "Chainlink (implied)", "price": implied, "method": "Oracle"})
    print(f"  Implied ETH/USDC: {implied:,.4f}")

# 4. Save to DB
print(f"\n[4] Saving to database...")
print("-" * 70)
DB_PATH = os.path.expanduser("~/.hermes/data/dex_prices.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('DROP TABLE IF EXISTS dex_prices')
c.execute('''CREATE TABLE dex_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    dex_name TEXT NOT NULL,
    method TEXT NOT NULL,
    price_usdc_per_eth REAL NOT NULL,
    pair TEXT,
    pool_address TEXT,
    fee_bps INTEGER,
    liquidity_usd REAL,
    volume_24h_usd REAL
)''')
c.execute('CREATE INDEX IF NOT EXISTS idx_ts ON dex_prices(timestamp)')
c.execute('CREATE INDEX IF NOT EXISTS idx_dex ON dex_prices(dex_name)')
now = time.time()
for r in results:
    c.execute('INSERT INTO dex_prices (timestamp, dex_name, method, price_usdc_per_eth, pair, pool_address, fee_bps, liquidity_usd) VALUES (?,?,?,?,?,?,?,?)',
              (now, r["dex"], r["method"], r["price"], r.get("pair"), r.get("pool"), r.get("fee_bps"), r.get("liquidity")))
conn.commit()
c.execute("SELECT COUNT(*) FROM dex_prices")
total = c.fetchone()[0]
c.execute("SELECT COUNT(DISTINCT dex_name) FROM dex_prices")
unique = c.fetchone()[0]
print(f"  DB: {DB_PATH}")
print(f"  Total records: {total}")
print(f"  Unique DEXes: {unique}")
conn.close()

# 5. Summary
print(f"\n{'='*70}")
print(f"  FINAL: {len(results)} sources across {len(set(r['dex'] for r in results))} DEXes")
print(f"{'='*70}")
results.sort(key=lambda x: x["price"])
print(f"\n  {'DEX':<30} {'Price':>12}  {'Method':<20} {'Pair'}")
print(f"  {'-'*30} {'-'*12}  {'-'*20} {'-'*10}")
for r in results:
    print(f"  {r['dex']:<30} {r['price']:>12,.2f}  {r['method']:<20} {r.get('pair', '')}")

if results:
    best = max(results, key=lambda x: x["price"])
    worst = min(results, key=lambda x: x["price"])
    spread = (best["price"] - worst["price"]) / worst["price"] * 100
    avg = sum(r["price"] for r in results) / len(results)
    print(f"\n  Best: {best['dex']} @ {best['price']:,.2f}")
    print(f"  Worst: {worst['dex']} @ {worst['price']:,.2f}")
    print(f"  Spread: {spread:.2f}% {'⚡' if spread > 0.5 else ''}")
    print(f"  Avg: {avg:,.2f}")

print(f"\n  Failed: {len(failed_dexes)}")
for dex in failed_dexes[:10]:
    print(f"    - {dex}")
if len(failed_dexes) > 10:
    print(f"    ... and {len(failed_dexes) - 10} more")

# Save snapshot
snapshot = {"timestamp": now, "chain": "base", "sources": len(results), "spread_pct": spread if results else 0, "results": results, "failed": failed_dexes}
with open(os.path.expanduser("~/.hermes/data/dex_snapshot.json"), "w") as f:
    json.dump(snapshot, f, indent=2)
print(f"\n  Snapshot saved to ~/.hermes/data/dex_snapshot.json")
