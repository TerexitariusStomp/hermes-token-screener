#!/usr/bin/env python3
"""BASE DEX PRICE FETCHER V8 - Live ETH/USDC prices from 9+ on-chain sources.
Sources: 3 V2 AMMs + 3 V3 AMMs + 1 AMO DEX + Chainlink oracle + Dexscreener API.
"""

import json, urllib.request, ssl, time, os
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "base-dex-config.json")
CACHE_PATH = os.path.join(SCRIPT_DIR, "base-dex-prices-cache.json")
DASHBOARD_DIR = os.path.expanduser("~/.hermes/dashboard")

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BULLET = "0x8f0347739c06a3A1bD69a31901AE0d9F041a7862"
CHAINLINK_ETH_USD = "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70"
SUSHI_V2_ROUTER = "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891"

V2_PAIRS = {
    "Uniswap V2":   "0x88a43bbdf9d098eec7bceda4e2494615dfd9bb9c",
    "PancakeSwap V2":"0x79474223aedd0339780bacce75abda0be84dcbf9",
    "Aerodrome Vol": "0xcdac0d6c6c59727a65f871236188350531885c43",
}

V3_FACTORIES = {
    "Uniswap V3":    {"factory":"0x33128a8fC17869897dcE68Ed026d694621f6FDfD", "fee":500},
    "SushiSwap V3":  {"factory":"0xc35DADB65012eC5796536bD9864eD8773aBc74C4", "fee":500},
    "PancakeSwap V3":{"factory":"0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865", "fee":100},
}

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
            payload = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode()
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = json.loads(resp.read().decode())
                if "result" in data and data["result"] not in [None, "0x", "", "0x0"]:
                    return data["result"]
            rpc_idx += 1
        except:
            rpc_idx += 1
            time.sleep(0.5)
    return None


def fetch_chainlink():
    """Chainlink ETH/USD aggregator latestAnswer (8 decimals)."""
    result = rpc_call("eth_call", [{"to": CHAINLINK_ETH_USD, "data": "0xfeaf968c"}, "latest"])
    if result and len(result) >= 130:
        val = int(result[66:130], 16)
        if val > 0:
            return round(val / 1e8, 2)
    return None


def fetch_v2_price(pair_addr):
    """V2 pair getReserves() -> ETH/USDC price."""
    result = rpc_call("eth_call", [{"to": pair_addr, "data": "0x0902f1ac"}, "latest"])
    if result and len(result) >= 194:
        r0 = int(result[2:66], 16)
        r1 = int(result[66:130], 16)
        if r0 > 0 and r1 > 0:
            # token0=WETH(18), token1=USDC(6)
            return round((r1 / 1e6) / (r0 / 1e18), 2)
    return None


def fetch_v3_price(factory, fee):
    """V3 factory.getPool() -> pool.slot0() -> ETH/USDC price."""
    data = "0x1698ee82" + WETH[2:].zfill(64) + USDC[2:].zfill(64) + hex(fee)[2:].zfill(64)
    result = rpc_call("eth_call", [{"to": factory, "data": data}, "latest"])
    if not result or len(result) < 66:
        return None, None
    pool = "0x" + result[26:66]
    if pool == "0x" + "0"*40:
        return None, None
    slot = rpc_call("eth_call", [{"to": pool, "data": "0x3850c7bd"}, "latest"])
    if slot and len(slot) >= 66:
        sqrt = int(slot[:66], 16)
        if sqrt > 0:
            spot = (sqrt / (2**96)) ** 2
            # token0=WETH, token1=USDC: spot = token1/token0
            price = spot * 1e12
            return round(price, 2), pool
    return None, pool


def fetch_sushi_v2_quote():
    """SushiSwap V2 getAmountsOut for 0.01 ETH -> USDC."""
    amount = hex(10**16)[2:].zfill(64)
    path_off = "0"*62 + "40"
    path_len = "0"*62 + "02"
    data = "0xd06ca61f" + amount + path_off + path_len + WETH[2:].zfill(64) + USDC[2:].zfill(64)
    result = rpc_call("eth_call", [{"to": SUSHI_V2_ROUTER, "data": data}, "latest"])
    if result and len(result) >= 258:
        out = int(result[194:258], 16)
        if out > 1000000:
            return round((out / 1e6) / 0.01, 2)
    return None


def fetch_dexscreener():
    """Dexscreener API for Bullet token."""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{BULLET}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            for p in (data.get("pairs") or []):
                if isinstance(p, dict) and p.get("chainId") == "base" and p.get("priceNative"):
                    return round(float(p["priceNative"]), 2)
    except:
        pass
    return None


def main():
    ts = datetime.now(timezone.utc).isoformat()
    sources = []

    # 1. Chainlink
    cl = fetch_chainlink()
    if cl: sources.append({"dex":"Chainlink Oracle","price":cl,"type":"oracle","pool":""})

    # 2. V2 pairs
    for dex, pair in V2_PAIRS.items():
        p = fetch_v2_price(pair)
        if p: sources.append({"dex":dex,"price":p,"type":"v2-amm","pool":pair})
        time.sleep(0.3)

    # 3. SushiSwap V2 via quoter
    sq = fetch_sushi_v2_quote()
    if sq: sources.append({"dex":"SushiSwap V2","price":sq,"type":"v2-amm","pool":SUSHI_V2_ROUTER})

    # 4. V3 pools
    for dex, cfg in V3_FACTORIES.items():
        p, pool = fetch_v3_price(cfg["factory"], cfg["fee"])
        if p: sources.append({"dex":dex,"price":p,"type":"v3-amm","pool":pool or ""})
        time.sleep(0.3)

    # 5. Dexscreener
    ds = fetch_dexscreener()
    if ds: sources.append({"dex":"Dexscreener","price":ds,"type":"api","pool":""})

    # Filter outliers (reject prices >2% from median)
    prices = [s["price"] for s in sources]
    if len(prices) >= 3:
        median = sorted(prices)[len(prices)//2]
        sources = [s for s in sources if abs(s["price"]-median)/median < 0.02]

    prices = [s["price"] for s in sources]
    if not prices:
        print("ERROR: No prices collected")
        return

    spread = round((max(prices) - min(prices)) / min(prices) * 100, 4)
    mean = round(sum(prices)/len(prices), 2)

    output = {
        "timestamp": ts,
        "sources": sorted(sources, key=lambda x: x["price"]),
        "statistics": {
            "min": min(prices),
            "max": max(prices),
            "mean": mean,
            "median": sorted(prices)[len(prices)//2],
            "spread_pct": spread,
            "count": len(prices),
        }
    }

    # Save cache
    with open(CACHE_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print(f" BASE DEX ETH/USDC PRICES — {ts[:19]}Z")
    print(f"{'='*60}")
    print(f" {'Source':<22} {'Price':>12} {'Type':<10}")
    print(f" {'-'*50}")
    for s in output["sources"]:
        print(f" {s['dex']:<22} {s['price']:>12,.2f} {s['type']:<10}")
    print(f" {'-'*50}")
    print(f" {'Mean':<22} {mean:>12,.2f}")
    print(f" {'Median':<22} {output['statistics']['median']:>12,.2f}")
    print(f" {'Spread':<22} {spread:>11.3f}%")
    print(f" {'Sources':<22} {len(prices):>12}")
    print(f"{'='*60}\n")

    # Generate dashboard
    generate_dashboard(output)


def generate_dashboard(data):
    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    sources_rows = ""
    for s in data["sources"]:
        color = "#00ff88" if abs(s["price"] - data["statistics"]["mean"])/data["statistics"]["mean"] < 0.005 else "#ffaa00"
        pool_link = f'<a href="https://basescan.org/address/{s["pool"]}" target="_blank">{s["pool"][:10]}...{s["pool"][-6:]}</a>' if s["pool"] else "—"
        sources_rows += f"""<tr>
            <td>{s["dex"]}</td>
            <td style="color:{color};font-weight:bold">${s["price"]:,.2f}</td>
            <td><span class="badge">{s["type"]}</span></td>
            <td class="mono">{pool_link}</td>
            <td>{round((s["price"]-data["statistics"]["mean"])/data["statistics"]["mean"]*100,3):+.3f}%</td>
        </tr>\n"""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Base DEX ETH/USDC Prices</title>
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
.badge{{background:#2a2a4a;padding:2px 8px;border-radius:4px;font-size:0.8em}}
.footer{{text-align:center;color:#555;font-size:0.8em;margin-top:20px}}
</style></head><body>
<div class="header">
    <h1>Base DEX ETH/USDC Live Prices</h1>
    <div class="ts">Updated: {data["timestamp"][:19]}Z | Sources: {data["statistics"]["count"]} on-chain + API</div>
</div>
<div class="stats">
    <div class="stat"><div class="val">${data["statistics"]["mean"]:,.2f}</div><div class="label">MEAN PRICE</div></div>
    <div class="stat"><div class="val">${data["statistics"]["median"]:,.2f}</div><div class="label">MEDIAN</div></div>
    <div class="stat spread"><div class="val">{data["statistics"]["spread_pct"]:.3f}%</div><div class="label">SPREAD</div></div>
    <div class="stat"><div class="val">${data["statistics"]["max"]-data["statistics"]["min"]:,.2f}</div><div class="label">MAX DEVIATION</div></div>
</div>
<table><thead><tr><th>Source</th><th>Price</th><th>Type</th><th>Pool / Oracle</th><th>Δ Mean</th></tr></thead>
<tbody>{sources_rows}</tbody></table>
<div class="footer">Read directly from Base L2 via {len(RPCS)} RPCs — no DEX API keys required.</div>
</body></html>"""

    with open(os.path.join(DASHBOARD_DIR, "dex-prices.html"), "w") as f:
        f.write(html)
    print(f"Dashboard: {os.path.join(DASHBOARD_DIR, 'dex-prices.html')}")


if __name__ == "__main__":
    main()
