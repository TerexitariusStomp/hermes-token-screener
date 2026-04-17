#!/usr/bin/env python3
"""BASE DEX PRICE FETCHER V9 — ETH/USDC from 28+ sources across 11+ DEXes.
Sources: Dexscreener API (9 DEXes) + on-chain V2/V3 + Chainlink + ParaSwap + CoinGecko.
"""

import json, urllib.request, ssl, time, os
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(SCRIPT_DIR, "base-dex-prices-cache.json")
DASHBOARD_DIR = os.path.expanduser("~/.hermes/dashboard")

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
CHAINLINK_ETH_USD = "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70"

RPCS = [
    "https://base.llamarpc.com",
    "https://base.drpc.org",
    "https://1rpc.io/base",
]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
rpc_idx = 0


def rpc_call(method, params=[]):
    global rpc_idx
    for _ in range(len(RPCS) * 2):
        try:
            url = RPCS[rpc_idx % len(RPCS)]
            payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = json.loads(resp.read().decode())
                if "result" in data and data["result"] not in [None, "0x", ""]:
                    return data["result"]
            rpc_idx += 1
        except:
            rpc_idx += 1
            time.sleep(0.5)
    return None


def fetch_chainlink():
    r = rpc_call("eth_call", [{"to": CHAINLINK_ETH_USD, "data": "0xfeaf968c"}, "latest"])
    if r and len(r) >= 130 and r != "0x":
        val = int(r[66:130], 16)
        if val > 0:
            return round(val / 1e8, 2)
    return None


def fetch_dexscreener():
    """Dexscreener: all WETH/USDC pairs on Base, deduplicated by DEX."""
    results = []
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{WETH}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            pairs = data.get("pairs") or []
            for p in pairs:
                qt = (p.get("quoteToken", {}).get("address", "")).lower()
                bt = (p.get("baseToken", {}).get("address", "")).lower()
                if USDC.lower() not in (qt, bt):
                    continue
                price = float(p.get("priceNative", 0))
                if price <= 0:
                    continue
                dex = p.get("dexId", "unknown").title()
                liq = float(p.get("liquidity", {}).get("usd", 0) or 0)
                vol24 = float(p.get("volume", {}).get("h24", 0) or 0)
                pair_addr = p.get("pairAddress", "")
                results.append({
                    "dex": dex,
                    "price": round(price, 2),
                    "liq": liq,
                    "vol24": vol24,
                    "pool": pair_addr,
                    "type": "dexscreener",
                })
    except Exception as e:
        print(f"  Dexscreener error: {e}")
    return results


def fetch_paraswap():
    """ParaSwap aggregator best quote."""
    url = (
        "https://apiv5.paraswap.io/prices/"
        f"?srcToken={WETH}&destToken={USDC}"
        "&amount=100000000000000000&srcDecimals=18&destDecimals=6"
        "&side=SELL&network=8453"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            dest = int(data.get("priceRoute", {}).get("destAmount", 0))
            if dest > 0:
                price = round((dest / 1e6) / 0.1, 2)
                # Extract DEXes used
                best = data.get("priceRoute", {}).get("bestRoute", [])
                dexes = []
                for route in best:
                    for swap in route.get("swaps", []):
                        for ex in swap.get("swapExchanges", []):
                            dexes.append(ex.get("exchange", "?"))
                return {
                    "dex": "ParaSwap",
                    "price": price,
                    "liq": 0,
                    "vol24": 0,
                    "pool": "",
                    "type": "aggregator",
                    "route": ", ".join(set(dexes)),
                }
    except Exception as e:
        print(f"  ParaSwap error: {e}")
    return None


def fetch_coingecko():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            price = data.get("ethereum", {}).get("usd", 0)
            if price > 0:
                return {
                    "dex": "CoinGecko",
                    "price": round(price, 2),
                    "liq": 0,
                    "vol24": 0,
                    "pool": "",
                    "type": "api",
                }
    except:
        pass
    return None


def fetch_onchain_pairs():
    """On-chain getReserves for known V2 pairs."""
    v2 = {
        "Uni V2": "0x88a43bbdf9d098eec7bceda4e2494615dfd9bb9c",
        "Pancake V2": "0x79474223aedd0339780bacce75abda0be84dcbf9",
        "Aerodrome Vol": "0xcdac0d6c6c59727a65f871236188350531885c43",
    }
    results = []
    for dex, pair in v2.items():
        r = rpc_call("eth_call", [{"to": pair, "data": "0x0902f1ac"}, "latest"])
        if r and len(r) >= 194:
            r0 = int(r[2:66], 16)
            r1 = int(r[66:130], 16)
            if r0 > 0 and r1 > 0:
                price = round((r1 / 1e6) / (r0 / 1e18), 2)
                results.append({
                    "dex": dex, "price": price, "liq": 0, "vol24": 0,
                    "pool": pair, "type": "on-chain-v2",
                })
        time.sleep(0.3)
    return results


def fetch_onchain_v3():
    """On-chain slot0 for known V3 pools."""
    v3 = {
        "Uni V3 (0.05%)": "0xd0b53d9277642d899df5c87a3966a349a798f224",
        "Sushi V3 (0.05%)": "0x57713f7716e0b0f65ec116912f834e49805480d2",
        "Pancake V3 (0.01%)": "0x72AB388E6C60Ed3617197beFa4e44F46f211984a",
        "Pancake V3 (0.05%)": "0xB775272E537cc670C65dc852908ad47015244eaf",
    }
    results = []
    for dex, pool in v3.items():
        r = rpc_call("eth_call", [{"to": pool, "data": "0x3850c7bd"}, "latest"])
        if r and len(r) >= 66 and r != "0x":
            sqrt = int(r[:66], 16)
            if sqrt > 0:
                spot = (sqrt / (2**96)) ** 2
                price = round(spot * 1e12, 2)
                results.append({
                    "dex": dex, "price": price, "liq": 0, "vol24": 0,
                    "pool": pool, "type": "on-chain-v3",
                })
        time.sleep(0.3)
    return results


BLOCKED_DEXES = {"iziswap"}  # Dead DEX: 1 pool, $95k liq, stale pricing

def deduplicate_dexscreener(sources):
    """Keep only the highest-liquidity pool per DEX from Dexscreener."""
    best = {}
    for s in sources:
        if s["type"] != "dexscreener":
            continue
        if s["dex"].lower() in BLOCKED_DEXES:
            continue
        key = s["dex"]
        if key not in best or s["liq"] > best[key]["liq"]:
            best[key] = s
    non_ds = [s for s in sources if s["type"] != "dexscreener"]
    return non_ds + list(best.values())


def filter_outliers(sources, threshold=0.015):
    """Remove sources >threshold away from median."""
    prices = [s["price"] for s in sources]
    if len(prices) < 5:
        return sources
    median = sorted(prices)[len(prices) // 2]
    return [s for s in sources if abs(s["price"] - median) / median < threshold]


def main():
    ts = datetime.now(timezone.utc).isoformat()
    all_sources = []

    print("Fetching prices from all sources...")

    # Layer 1: Chainlink oracle
    cl = fetch_chainlink()
    if cl:
        all_sources.append({"dex": "Chainlink", "price": cl, "liq": 0, "vol24": 0,
                           "pool": CHAINLINK_ETH_USD, "type": "oracle"})
        print(f"  Chainlink: ${cl:,.2f}")

    # Layer 2: Dexscreener (covers 9+ DEXes in 1 call)
    ds = fetch_dexscreener()
    print(f"  Dexscreener: {len(ds)} pairs")
    all_sources.extend(ds)

    # Layer 3: ParaSwap aggregator
    ps = fetch_paraswap()
    if ps:
        all_sources.append(ps)
        print(f"  ParaSwap: ${ps['price']:,.2f}")

    # Layer 4: CoinGecko
    cg = fetch_coingecko()
    if cg:
        all_sources.append(cg)
        print(f"  CoinGecko: ${cg['price']:,.2f}")

    # Layer 5: On-chain V2 pairs
    v2 = fetch_onchain_pairs()
    print(f"  On-chain V2: {len(v2)} pairs")
    all_sources.extend(v2)

    # Layer 6: On-chain V3 pools
    v3 = fetch_onchain_v3()
    print(f"  On-chain V3: {len(v3)} pools")
    all_sources.extend(v3)

    # Deduplicate Dexscreener by DEX (keep highest-liq pool each)
    all_sources = deduplicate_dexscreener(all_sources)

    # Filter extreme outliers (>1.5% from median)
    all_sources = filter_outliers(all_sources, threshold=0.015)

    prices = [s["price"] for s in all_sources if 1000 < s["price"] < 10000]
    if not prices:
        print("ERROR: No valid prices collected")
        return

    spread = round((max(prices) - min(prices)) / min(prices) * 100, 4)
    mean = round(sum(prices) / len(prices), 2)

    output = {
        "timestamp": ts,
        "sources": sorted(all_sources, key=lambda x: x["price"]),
        "statistics": {
            "min": min(prices),
            "max": max(prices),
            "mean": mean,
            "median": sorted(prices)[len(prices) // 2],
            "spread_pct": spread,
            "count": len(prices),
        }
    }

    with open(CACHE_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Print
    print(f"\n{'='*65}")
    print(f" BASE DEX ETH/USDC — {ts[:19]}Z — {len(prices)} sources")
    print(f"{'='*65}")
    print(f" {'#':<4}{'Source':<25}{'Price':>12}{'Liq':>12}{'Type'}")
    print(f" {'-'*60}")
    for i, s in enumerate(sorted(all_sources, key=lambda x: x["price"]), 1):
        liq = f"${s['liq']:,.0f}" if s["liq"] > 0 else "—"
        print(f" {i:<4}{s['dex']:<25}{s['price']:>12,.2f}{liq:>12}{s['type']}")
    print(f" {'-'*60}")
    print(f" {'Mean':<29}{mean:>12,.2f}")
    print(f" {'Median':<29}{output['statistics']['median']:>12,.2f}")
    print(f" {'Spread':<29}{spread:>11.3f}%")
    print(f"{'='*65}\n")

    generate_dashboard(output)
    return output


def generate_dashboard(data):
    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    sources_rows = ""
    mean = data["statistics"]["mean"]
    for s in data["sources"]:
        dev = (s["price"] - mean) / mean * 100 if mean else 0
        color = "#00ff88" if abs(dev) < 0.3 else "#ffaa00" if abs(dev) < 1 else "#ff4444"
        liq = f"${s['liq']:,.0f}" if s.get("liq", 0) > 0 else "—"
        pool_link = (f'<a href="https://basescan.org/address/{s["pool"]}" target="_blank">'
                     f'{s["pool"][:10]}...{s["pool"][-6:]}</a>') if s.get("pool") else "—"
        badge_color = {"dexscreener": "#4a90d9", "on-chain-v2": "#00cc88", "on-chain-v3": "#00cc88",
                       "oracle": "#ff8800", "aggregator": "#aa66ff", "api": "#888"}.get(s["type"], "#666")
        sources_rows += f"""<tr>
            <td>{s["dex"]}</td>
            <td style="color:{color};font-weight:bold">${s["price"]:,.2f}</td>
            <td>{liq}</td>
            <td><span class="badge" style="border-color:{badge_color}">{s["type"]}</span></td>
            <td class="mono">{pool_link}</td>
            <td style="color:{color}">{dev:+.2f}%</td>
        </tr>\n"""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Base DEX ETH/USDC Prices — {data["statistics"]["count"]} Sources</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a1a;color:#e0e0e0;font-family:'JetBrains Mono',monospace;padding:20px}}
.header{{text-align:center;margin-bottom:30px}}
.header h1{{color:#00ff88;font-size:1.8em}}
.header .ts{{color:#888;font-size:0.9em}}
.stats{{display:flex;justify-content:center;gap:20px;margin-bottom:30px;flex-wrap:wrap}}
.stat{{background:#1a1a2e;border:1px solid #2a2a4a;border-radius:8px;padding:15px 25px;text-align:center;min-width:150px}}
.stat .val{{font-size:1.8em;color:#00ff88;font-weight:bold}}
.stat .label{{color:#888;font-size:0.8em;margin-top:5px}}
.spread{{border-color:{'#00ff88' if data['statistics']['spread_pct']<0.5 else '#ffaa00' if data['statistics']['spread_pct']<1 else '#ff4444'}}}
.spread .val{{color:{'#00ff88' if data['statistics']['spread_pct']<0.5 else '#ffaa00' if data['statistics']['spread_pct']<1 else '#ff4444'}}}
table{{width:100%;border-collapse:collapse;background:#1a1a2e;border-radius:8px;overflow:hidden}}
th{{background:#2a2a4a;padding:12px;text-align:left;font-size:0.85em;color:#aaa}}
td{{padding:10px 12px;border-bottom:1px solid #1f1f3a}}
tr:hover{{background:#252545}}
.mono{{font-size:0.8em}}
.mono a{{color:#6688cc;text-decoration:none}}
.badge{{background:#2a2a4a;padding:2px 8px;border-radius:4px;font-size:0.8em;border:1px solid #555}}
.footer{{text-align:center;color:#555;font-size:0.8em;margin-top:20px}}
</style></head><body>
<div class="header">
    <h1>Base DEX ETH/USDC — {data["statistics"]["count"]} Live Sources</h1>
    <div class="ts">Updated: {data["timestamp"][:19]}Z</div>
</div>
<div class="stats">
    <div class="stat"><div class="val">${data["statistics"]["mean"]:,.2f}</div><div class="label">MEAN</div></div>
    <div class="stat"><div class="val">${data["statistics"]["median"]:,.2f}</div><div class="label">MEDIAN</div></div>
    <div class="stat spread"><div class="val">{data["statistics"]["spread_pct"]:.3f}%</div><div class="label">SPREAD</div></div>
    <div class="stat"><div class="val">${data["statistics"]["max"]-data["statistics"]["min"]:,.2f}</div><div class="label">MAX DEVIATION</div></div>
</div>
<table><thead><tr><th>Source</th><th>Price</th><th>Liquidity</th><th>Type</th><th>Contract</th><th>Δ Mean</th></tr></thead>
<tbody>{sources_rows}</tbody></table>
<div class="footer">Dexscreener API + on-chain V2/V3 + Chainlink + ParaSwap + CoinGecko</div>
</body></html>"""

    with open(os.path.join(DASHBOARD_DIR, "dex-prices.html"), "w") as f:
        f.write(html)
    print(f"Dashboard: {DASHBOARD_DIR}/dex-prices.html")


if __name__ == "__main__":
    main()
