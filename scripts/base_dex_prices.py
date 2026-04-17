#!/usr/bin/env python3
"""
Base DEX Price Fetcher v3
Factory-based pool discovery + multi-pair quotes from all verified DEXes.
Discovers pools dynamically, quotes from working routers.

Usage: python base_dex_prices.py [--amount 0.01] [--all-pairs] [--json]
"""

import json
import urllib.request
import ssl
import time
import argparse

RPCS = ["https://base.llamarpc.com", "https://base.drpc.org", "https://1rpc.io/base"]
rpc_idx = 0
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def rpc_call(method, params=[]):
    global rpc_idx
    for _ in range(4):
        try:
            url = RPCS[rpc_idx % len(RPCS)]
            payload = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                return json.loads(resp.read().decode())
        except:
            rpc_idx += 1
            time.sleep(0.5)
    return {"error": "failed"}

def call(to, data):
    r = rpc_call("eth_call", [{"to": to, "data": data}, "latest"])
    return r.get("result", "0x")

TOKENS = {
    "WETH":  ("0x4200000000000000000000000000000000000006", 18),
    "USDC":  ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
    "USDT":  ("0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2", 6),
    "DAI":   ("0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", 18),
    "AERO":  ("0x940181a94A35A4569D4521129DfD34b47d5Ed16c", 18),
    "cbETH": ("0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22", 18),
    "cbBTC": ("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8),
    "USDbC": ("0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA", 6),
}

# DEX factories to scan
FACTORIES = {
    "Uniswap V2":     {"type": "v2", "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6", "router": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"},
    "Aerodrome":      {"type": "v2", "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da", "router": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"},
    "BaseSwap V2":    {"type": "v2", "factory": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB", "router": "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86"},
    "PancakeSwap V2": {"type": "v2", "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6", "router": "0x8cFe327CEc66d1C090Dd72bd0FF11d690C33a2Eb"},
    "SushiSwap V2":   {"type": "v2", "factory": "0x71524B4f93c58fcbF659783fCBe56AcF49992dDa", "router": "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891"},
    "Uniswap V3":     {"type": "v3", "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD", "quoter": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"},
    "PancakeSwap V3": {"type": "v3", "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865", "quoter": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"},
}

PAIRS = [
    ("WETH", "USDC", [500, 3000, 10000, 100]),
    ("WETH", "DAI", [500, 3000, 10000]),
    ("WETH", "USDT", [500, 3000, 10000]),
    ("WETH", "AERO", [500, 3000, 10000, 100]),
    ("WETH", "cbETH", [500, 3000, 100]),
    ("USDC", "USDT", [100, 500, 3000]),
    ("USDC", "DAI", [100, 500, 3000]),
    ("WETH", "cbBTC", [500, 3000, 100]),
]

def check_v2(factory, tA, tB):
    data = "0xe6a43905" + tA[2:].zfill(64) + tB[2:].zfill(64)
    r = call(factory, data)
    if r and len(r) >= 66:
        addr = "0x" + r[26:66]
        return addr if addr != "0x" + "0"*40 else None
    return None

def check_v3(factory, tA, tB, fee):
    data = "0x1698ee82" + tA[2:].zfill(64) + tB[2:].zfill(64) + hex(fee)[2:].zfill(64)
    r = call(factory, data)
    if r and len(r) >= 66:
        addr = "0x" + r[26:66]
        return addr if addr != "0x" + "0"*40 else None
    return None

def quote_v2(router, tA, tB, amount_wei):
    path_off = "0"*62 + "40"
    path_len = "0"*62 + "02"
    data = "0xd06ca61f" + hex(amount_wei)[2:].zfill(64) + path_off + path_len + tA[2:].zfill(64) + tB[2:].zfill(64)
    r = call(router, data)
    if r and len(r) >= 258:
        try:
            if int(r[66:130], 16) >= 2:
                return int(r[194:258], 16)
        except:
            pass
    return None

def quote_v3(quoter, tA, tB, fee, amount_wei):
    data = "0xf7729d43" + tA[2:].zfill(64) + tB[2:].zfill(64) + hex(fee)[2:].zfill(64) + hex(amount_wei)[2:].zfill(64) + "0"*64
    r = call(quoter, data)
    if r and len(r) >= 66:
        return int(r, 16)
    return None

def discover_and_quote(verbose=True):
    # Step 1: Discover all pools
    pools = []
    if verbose:
        print("=== POOL DISCOVERY ===\n")
    
    for dex, cfg in FACTORIES.items():
        for tA_name, tB_name, fees in PAIRS:
            tA = TOKENS[tA_name][0]
            tB = TOKENS[tB_name][0]
            
            if cfg["type"] == "v2":
                pool = check_v2(cfg["factory"], tA, tB)
                if pool:
                    pools.append({"dex": dex, "pair": f"{tA_name}-{tB_name}", "pool": pool, "type": "v2", "config": cfg, "fee": None})
                    if verbose:
                        print(f"  {dex:<20} {tA_name}-{tB_name:<12} V2  pool={pool[:20]}...")
            
            elif cfg["type"] == "v3":
                for fee in fees:
                    pool = check_v3(cfg["factory"], tA, tB, fee)
                    if pool:
                        pools.append({"dex": dex, "pair": f"{tA_name}-{tB_name}", "pool": pool, "type": "v3", "config": cfg, "fee": fee})
                        if verbose:
                            print(f"  {dex:<20} {tA_name}-{tB_name:<12} V3  fee={fee}bps  pool={pool[:20]}...")
            
            time.sleep(0.15)
    
    if verbose:
        print(f"\nDiscovered {len(pools)} pools across {len(FACTORIES)} factories\n")
    
    # Step 2: Quote all discovered pools
    results = []
    if verbose:
        print("=== PRICE QUOTES ===\n")
        print(f"{'DEX':<20}{'Pair':<14}{'Fee':<8}{'Price':>14}{'Amount Out':>14}")
        print("=" * 68)
    
    for pool_info in pools:
        dex = pool_info["dex"]
        pair = pool_info["pair"]
        config = pool_info["config"]
        tA_name, tB_name = pair.split("-")
        tA = TOKENS[tA_name][0]
        tB = TOKENS[tB_name][0]
        dec_out = TOKENS[tB_name][1]
        
        amount_wei = int(0.01 * 10**TOKENS[tA_name][1])
        
        if pool_info["type"] == "v2":
            out = quote_v2(config["router"], tA, tB, amount_wei)
            fee_str = "V2"
        else:
            out = quote_v3(config["quoter"], tA, tB, pool_info["fee"], amount_wei)
            fee_str = f"{pool_info['fee']}"
        
        if out and out > 0:
            out_amt = out / (10 ** dec_out)
            price = out_amt / 0.01
            results.append({"dex": dex, "pair": pair, "price": price, "out": out_amt, "fee": fee_str})
            if verbose:
                print(f"{dex:<20}{pair:<14}{fee_str:<8}{price:>14,.2f}{out_amt:>14,.6f}")
        else:
            if verbose:
                print(f"{dex:<20}{pair:<14}{fee_str:<8}{'FAIL':>14}{'':>14}")
        
        time.sleep(0.2)
    
    # Summary
    if verbose and results:
        print(f"\n=== SUMMARY ===\n")
        pairs_set = sorted(set(r["pair"] for r in results))
        for pair in pairs_set:
            pr = [r for r in results if r["pair"] == pair]
            prices = [r["price"] for r in pr]
            spread = (max(prices) - min(prices)) / min(prices) * 100
            best = max(pr, key=lambda x: x["price"])
            print(f"{pair}: {len(pr)} quotes, spread {spread:.2f}%, best @ {best['dex']} ({best['price']:,.2f})")
    
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    
    block = rpc_call("eth_blockNumber")
    if "result" in block:
        print(f"Base block: {int(block['result'], 16):,}\n")
    
    results = discover_and_quote(not args.json)
    
    if args.json:
        print(json.dumps(results, indent=2))
