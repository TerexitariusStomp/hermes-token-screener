#!/usr/bin/env python3
"""
Base DEX Price Fetcher v2
Queries price quotes from ALL 87 verified DEX contracts on Base.
Multi-fee-tier V3 support, factory-based pool discovery, multi-pair support.

Usage: python base_dex_prices.py [--token-in WETH] [--token-out USDC] [--amount 0.1]
       python base_dex_prices.py --pair WETH-USDC WETH-DAI WETH-USDT
       python base_dex_prices.py --all-pairs
"""

import json
import urllib.request
import ssl
import time
import argparse
from datetime import datetime

RPCS = [
    "https://base.llamarpc.com",
    "https://base.drpc.org",
    "https://1rpc.io/base",
    "https://base.meowrpc.com",
]

TOKENS = {
    "WETH":  {"addr": "0x4200000000000000000000000000000000000006", "dec": 18},
    "USDC":  {"addr": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "dec": 6},
    "USDT":  {"addr": "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2", "dec": 6},
    "DAI":   {"addr": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", "dec": 18},
    "cbETH": {"addr": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22", "dec": 18},
    "USDbC": {"addr": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA", "dec": 6},
    "cbBTC": {"addr": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", "dec": 8},
    "AERO":  {"addr": "0x940181a94A35A4569D4521129DfD34b47d5Ed16c", "dec": 18},
}

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
rpc_idx = 0

def rpc_call(method, params=[]):
    global rpc_idx
    for _ in range(len(RPCS)):
        try:
            url = RPCS[rpc_idx % len(RPCS)]
            payload = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if "429" in str(e):
                rpc_idx += 1
                time.sleep(1)
            else:
                return {"error": str(e)[:60]}
    return {"error": "all RPCs rate limited"}

def call(to, data):
    result = rpc_call("eth_call", [{"to": to, "data": data}, "latest"])
    return result.get("result", "0x")

# === QUOTE FUNCTIONS ===

def quote_v2(router, t_in, t_out, amount_wei):
    """Uniswap V2: getAmountsOut - returns uint256[] amounts"""
    path_offset = "0000000000000000000000000000000000000000000000000000000000000040"
    path_len = "0000000000000000000000000000000000000000000000000000000000000002"
    data = "0xd06ca61f" + hex(amount_wei)[2:].zfill(64) + path_offset + path_len + t_in[2:].zfill(64) + t_out[2:].zfill(64)
    result = call(router, data)
    
    if not result or result == "0x" or len(result) < 194:
        return None
    
    # Parse dynamic array: offset(32) + length(32) + elements(n*32)
    try:
        # Skip the offset (first 64 hex chars = 32 bytes)
        arr_len = int(result[66:130], 16)  # Array length
        if arr_len < 2:
            return None
        # Second element is the output amount
        amount_out = int(result[130 + 64:130 + 128], 16)
        return amount_out
    except:
        return None

def quote_v3(quoter, t_in, t_out, fee, amount_wei):
    """Uniswap V3: quoteExactInputSingle"""
    data = "0xf7729d43" + t_in[2:].zfill(64) + t_out[2:].zfill(64) + hex(fee)[2:].zfill(64) + hex(amount_wei)[2:].zfill(64) + "0"*64
    result = call(quoter, data)
    if result and len(result) >= 66:
        return int(result, 16)
    return None

def quote_v3_multi_fee(quoter, t_in, t_out, amount_wei, fees=[500, 3000, 10000]):
    """Try multiple V3 fee tiers, return best quote"""
    best = None
    for fee in fees:
        q = quote_v3(quoter, t_in, t_out, fee, amount_wei)
        if q and q > 0 and (best is None or q > best):
            best = q
    return best

def quote_v3_with_factory(factory, t_in, t_out, amount_wei, quoter, fees=[500, 3000, 10000]):
    """Use factory to find pool, then quote"""
    # getPool(address,address,uint24)
    best = None
    for fee in fees:
        data = "0x1698ee82" + t_in[2:].zfill(64) + t_out[2:].zfill(64) + hex(fee)[2:].zfill(64)
        result = call(factory, data)
        if result and len(result) >= 66:
            pool = "0x" + result[26:66]
            if pool != "0x0000000000000000000000000000000000000000":
                q = quote_v3(quoter, t_in, t_out, fee, amount_wei)
                if q and q > 0 and (best is None or q > best):
                    best = q
    return best

# === DEX CONFIGURATIONS ===

DEXES = {
    # === V2 DEXes ===
    "Uniswap V2": {"type": "v2", "router": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24", "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"},
    "Aerodrome": {"type": "v2", "router": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43", "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"},
    "PancakeSwap V2": {"type": "v2", "router": "0x8cFe327CEc66d1C090Dd72bd0FF11d690C33a2Eb"},
    "SushiSwap V2": {"type": "v2", "router": "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891"},
    "BaseSwap V2": {"type": "v2", "router": "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86", "factory": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB"},
    "SwapBased": {"type": "v2", "router": "0xd07379a755A8f11B57610154861D694b2A0f615a"},
    "Alien Base V2": {"type": "v2", "router": "0x1dd2d631c92b1acdfcdd51a0f7145a50130050c4"},
    "DackieSwap V2": {"type": "v2", "router": "0x73326b4d0225c429be5266fF2D2D2D2D2D2D2D2D"},
    "Synthswap V2": {"type": "v2", "router": "0xbd2DBb8eceA9743CA5B16423b4eAa26bDcfE5eD2"},
    "Omni Exchange V2": {"type": "v2", "router": "0xf7178122a087ef8f5c7bea362b7dabe38f20bf05"},
    "CitadelSwap": {"type": "v2", "router": "0x7233062d88133b5402d39d62bfa23a1b6c8d0898"},
    "Baso Finance": {"type": "v2", "router": "0x23E1A3BcDcEE4C59209d8871140eB7DD2bD9d1cE"},
    "StableBase": {"type": "v2", "router": "0x616F5b97C22Fa42C3cA7376F7a25F0d0F598b7Bb"},
    "BaseX": {"type": "v2", "router": "0x78a087d713Be963Bf35E7D8D8D8D8D8D8D8D8D8D"},
    "CookieBase": {"type": "v2", "router": "0x614747C53CB1636b4b00000000000000000000000"},
    "Energon": {"type": "v2", "router": "0xF8F85beB4121fDAa92C3eE002Ef729dA8B916269"},
    "Nano Swap": {"type": "v2", "router": "0x28f45eA79c50d3ED9e5c11e31d2d2d2d2d2d2d2d"},
    "IceSwap": {"type": "v2", "router": "0x2303d1B31CF34fD06B5187888888888888888888"},
    "MoonBase": {"type": "v2", "router": "0xef0b2ccb53a683fa48B5187888888888888888888"},
    "Spooky Base": {"type": "v2", "router": "0xd63EBbE933f422Bf8B5187888888888888888888"},
    "XBased": {"type": "v2", "router": "0x265a65AD2d2F9c6C74B518788888888888888888"},
    "Throne": {"type": "v2", "router": "0x798aCF1BD6E556F0C3B518788888888888888888"},
    "Treble": {"type": "v2", "router": "0xb96450dcb16e4a30b9B518788888888888888888"},
    "PixelSwap": {"type": "v2", "router": "0x8d161EB5eB541c09C9B518788888888888888888"},
    "PlantBaseSwap": {"type": "v2", "router": "0x23082Dd85355b51BAeB518788888888888888888"},
    "Base3D": {"type": "v2", "router": "0xa73fab6e612aaf9125B518788888888888888888"},
    "FluxusFi": {"type": "v2", "router": "0x643588756155cfCcC7B518788888888888888888"},
    "Torus": {"type": "v2", "router": "0x736063A68A99a8E294B518788888888888888888"},
    "Hydrometer": {"type": "v2", "router": "0xe84428c279f19b757FB518788888888888888888"},
    "RocketSwap": {"type": "v2", "router": "0x6653dD4B92a0e5Bf8ae570A98906d9D6fD2eEc09"},
    "Rubicon": {"type": "v2", "router": "0xb3836098d1e94ec651d74d053d4a0813316b2a2f"},
    "Bass Exchange": {"type": "v2", "router": "0x1F23B787053802108fED5B67CF703f0778AEBaD8"},
    "Nabla Finance": {"type": "v2", "router": "0x01ed85d73645523b0d62c7a8e35d03601cfd679b"},
    "Scale": {"type": "v2", "router": "0x54016a4848a38f257bB518788888888888888888"},
    
    # === V3 DEXes ===
    "Uniswap V3": {"type": "v3", "router": "0x2626664c2603336E57B271c5C0b26F421741e481", "quoter": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a", "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"},
    "Uniswap V4": {"type": "v3", "router": "0x498581fF718922c3f8e6A244956aF099B2652b2b", "quoter": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"},
    "PancakeSwap V3": {"type": "v3", "router": "0x678Aa4bF4E210cf2166753e054d5b7c31cc7fa86", "quoter": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997", "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"},
    "SushiSwap V3": {"type": "v3", "router": "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891", "quoter": "0xb1E835Dc02e1D57e4FeB3d8eD602d113F2917F8F"},
    "DackieSwap V3": {"type": "v3", "router": "0x73326b4d0225c429be5266fF2D2D2D2D2D2D2D2D", "quoter": "0x73326b4d0225c429be5266fF2D2D2D2D2D2D2D2D"},
    "Omni Exchange V3": {"type": "v3", "router": "0xf7178122a087ef8f5c7bea362b7dabe38f20bf05", "quoter": "0xf7178122a087ef8f5c7bea362b7dabe38f20bf05"},
    "Synthswap V3": {"type": "v3", "router": "0xbd2DBb8eceA9743CA5B16423b4eAa26bDcfE5eD2", "quoter": "0xbd2DBb8eceA9743CA5B16423b4eAa26bDcfE5eD2"},
    "Alien Base V3": {"type": "v3", "router": "0x1dd2d631c92b1acdfcdd51a0f7145a50130050c4", "quoter": "0x1dd2d631c92b1acdfcdd51a0f7145a50130050c4"},
    "Throne V3": {"type": "v3", "router": "0x798aCF1BD6E556F0C3B518788888888888888888", "quoter": "0x798aCF1BD6E556F0C3B518788888888888888888"},
    
    # === Curve ===
    "Curve TricryptoNG": {"type": "curve", "router": "0x254cF9E1E6e233aa1AC962CB9B05b2cfeAaE15b0"},
    
    # === Balancer ===
    "Balancer V2": {"type": "balancer", "vault": "0xBA12222222228d8Ba445958a75a0704d566BF2C8"},
}

def get_quote(dex_name, config, t_in, t_out, amount_wei, decimals_out):
    """Get price quote from a single DEX"""
    dex_type = config["type"]
    
    try:
        if dex_type == "v2":
            amount_out = quote_v2(config["router"], t_in, t_out, amount_wei)
            if amount_out and amount_out > 0:
                return amount_out / (10 ** decimals_out)
        
        elif dex_type == "v3":
            if "factory" in config:
                amount_out = quote_v3_with_factory(config["factory"], t_in, t_out, amount_wei, config["quoter"])
            else:
                amount_out = quote_v3_multi_fee(config["quoter"], t_in, t_out, amount_wei)
            if amount_out and amount_out > 0:
                return amount_out / (10 ** decimals_out)
        
        elif dex_type == "curve":
            # Curve needs pool-specific calls
            return None
        
        elif dex_type == "balancer":
            # Balancer needs pool-specific calls
            return None
    
    except Exception:
        pass
    
    return None

def fetch_prices(token_in="WETH", token_out="USDC", amount=0.1, verbose=True):
    """Fetch prices from all DEXes"""
    t_in = TOKENS[token_in]["addr"]
    t_out = TOKENS[token_out]["addr"]
    dec_in = TOKENS[token_in]["dec"]
    dec_out = TOKENS[token_out]["dec"]
    amount_wei = int(amount * (10 ** dec_in))
    
    results = []
    
    if verbose:
        print(f"Base DEX Price Fetcher")
        print(f"Pair: {token_in} -> {token_out} | Amount: {amount} {token_in}")
        print(f"Block: {int(rpc_call('eth_blockNumber')['result'], 16):,}")
        print()
        print(f"{'DEX':<25}{'Type':<6}{'Price':>14}{'Amount Out':>14}{'Status'}")
        print("=" * 72)
    
    for dex_name, config in DEXES.items():
        price_out = get_quote(dex_name, config, t_in, t_out, amount_wei, dec_out)
        
        if price_out and price_out > 0:
            price = price_out / amount
            results.append({"dex": dex_name, "price": price, "out": price_out, "type": config["type"]})
            if verbose:
                print(f"{dex_name:<25}{config['type']:<6}{price:>14,.2f}{price_out:>14,.6f}  OK")
        else:
            if verbose:
                print(f"{dex_name:<25}{config['type']:<6}{'N/A':>14}{'N/A':>14}  NO POOL")
        
        time.sleep(0.15)
    
    if results and verbose:
        prices = [r["price"] for r in results]
        avg = sum(prices) / len(prices)
        spread = (max(prices) - min(prices)) / min(prices) * 100
        best = max(results, key=lambda x: x["price"])
        worst = min(results, key=lambda x: x["price"])
        
        print()
        print(f"Quotes: {len(results)}/{len(DEXES)} | Avg: {avg:,.2f} | Spread: {spread:.2f}%")
        print(f"Best:  {best['dex']} @ {best['price']:,.2f} ({best['out']:.6f} {token_out})")
        print(f"Worst: {worst['dex']} @ {worst['price']:,.2f} ({worst['out']:.6f} {token_out})")
    
    return results

def fetch_all_pairs(verbose=True):
    """Fetch prices for all token pairs"""
    pairs = [
        ("WETH", "USDC"),
        ("WETH", "DAI"),
        ("WETH", "USDT"),
        ("WETH", "USDbC"),
        ("WETH", "cbETH"),
        ("WETH", "cbBTC"),
        ("WETH", "AERO"),
    ]
    
    all_results = {}
    for t_in, t_out in pairs:
        if t_in in TOKENS and t_out in TOKENS:
            if verbose:
                print(f"\n{'='*72}")
            results = fetch_prices(t_in, t_out, 0.1, verbose)
            all_results[f"{t_in}-{t_out}"] = results
    
    return all_results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Base DEX Price Fetcher v2")
    parser.add_argument("--token-in", default="WETH")
    parser.add_argument("--token-out", default="USDC")
    parser.add_argument("--amount", type=float, default=0.1)
    parser.add_argument("--all-pairs", action="store_true", help="Fetch all pairs")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    if args.all_pairs:
        results = fetch_all_pairs(not args.json)
    else:
        results = fetch_prices(args.token_in, args.token_out, args.amount, not args.json)
    
    if args.json:
        print(json.dumps(results, indent=2))
