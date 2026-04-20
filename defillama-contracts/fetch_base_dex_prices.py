#!/usr/bin/env python3
"""
Fetch prices from Base DEX contracts.
Tests all known Base DEX contracts to get price info on the top liquidity pool.
"""

import sys
import json
from pathlib import Path
from web3 import Web3
from decimal import Decimal

base_dir = Path.home() / ".hermes" / "defillama-contracts"
sys.path.insert(0, str(base_dir))

# Base RPC endpoints
BASE_RPCS = [
    "https://mainnet.base.org",
    "https://base.llamarpc.com",
    "https://base.drpc.org",
    "https://base-mainnet.public.blastapi.io",
]

# Common token addresses on Base
BASE_TOKENS = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "USDT": "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2",
    "cbETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
}

# DEX contract ABIs (simplified for price fetching)
ROUTER_ABI = [
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"}
        ],
        "name": "getAmountsOut",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "WETH",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "factory",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
]

FACTORY_ABI = [
    {
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"}
        ],
        "name": "getPair",
        "outputs": [{"name": "pair", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "allPairsLength",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
]

PAIR_ABI = [
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
]

# Known Base DEX contracts
KNOWN_BASE_DEXES = {
    # Aerodrome
    "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43": {
        "protocol": "Aerodrome", 
        "role": "router",
        "type": "dex",
    },
    "0x420DD381b31aEf6683db6B902084cB0FFECe40Da": {
        "protocol": "Aerodrome", 
        "role": "factory",
        "type": "dex",
    },
    # Uniswap V3
    "0x2626664c2603336E57B271c5C0b26F421741e481": {
        "protocol": "Uniswap V3", 
        "role": "router",
        "type": "dex",
    },
    "0x33128a8fC17869897dcE68Ed026d694621f6FDfD": {
        "protocol": "Uniswap V3", 
        "role": "factory",
        "type": "dex",
    },
    # Uniswap V2
    "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24": {
        "protocol": "Uniswap V2", 
        "role": "router",
        "type": "dex",
    },
    "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6": {
        "protocol": "Uniswap V2", 
        "role": "factory",
        "type": "dex",
    },
    # SushiSwap
    "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891": {
        "protocol": "SushiSwap", 
        "role": "router",
        "type": "dex",
    },
    "0x71524B4f93c58fcbF659783284E38825f0622859": {
        "protocol": "SushiSwap", 
        "role": "factory",
        "type": "dex",
    },
    # BaseSwap
    "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86": {
        "protocol": "BaseSwap", 
        "role": "router",
        "type": "dex",
    },
    "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB": {
        "protocol": "BaseSwap", 
        "role": "factory",
        "type": "dex",
    },
    # PancakeSwap
    "0x678Aa4bF4E210cf2166753e054d5b7c31cc7fa86": {
        "protocol": "PancakeSwap", 
        "role": "router",
        "type": "dex",
    },
    "0x02a84c1b3BBD7401a5f7fa98a384EBC70bB5749E": {
        "protocol": "PancakeSwap", 
        "role": "factory",
        "type": "dex",
    },
    # SwapBased
    "0xaaa3b1F1bd7BCc97fD1917c1816604fEBD082DEC": {
        "protocol": "SwapBased", 
        "role": "router",
        "type": "dex",
    },
    "0x04C9f118d21e8B767D2e50C946f0cC9F6C367300": {
        "protocol": "SwapBased", 
        "role": "factory",
        "type": "dex",
    },
}

def get_token_symbol(w3, token_address):
    """Get token symbol from address."""
    try:
        # ERC20 symbol() function
        abi = [{
            "inputs": [],
            "name": "symbol",
            "outputs": [{"name": "", "type": "string"}],
            "stateMutability": "view",
            "type": "function"
        }]
        contract = w3.eth.contract(address=token_address, abi=abi)
        return contract.functions.symbol().call()
    except:
        return token_address[:10] + "..."

def get_token_decimals(w3, token_address):
    """Get token decimals from address."""
    try:
        # ERC20 decimals() function
        abi = [{
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "stateMutability": "view",
            "type": "function"
        }]
        contract = w3.eth.contract(address=token_address, abi=abi)
        return contract.functions.decimals().call()
    except:
        return 18  # Default to 18 decimals

def test_dex_router(w3, router_address, protocol):
    """Test a DEX router for price fetching."""
    print(f"\n{'='*60}")
    print(f"Testing {protocol} Router")
    print(f"Address: {router_address}")
    print(f"{'='*60}")
    
    results = {
        "protocol": protocol,
        "role": "router",
        "address": router_address,
        "prices": {}
    }
    
    try:
        # Create contract instance
        router = w3.eth.contract(address=router_address, abi=ROUTER_ABI)
        
        # Test 1: Get WETH address
        try:
            weth_address = router.functions.WETH().call()
            results["weth_address"] = weth_address
            print(f"✓ WETH address: {weth_address}")
        except Exception as e:
            results["weth_address"] = None
            print(f"✗ Could not get WETH: {e}")
        
        # Test 2: Get factory address
        try:
            factory_address = router.functions.factory().call()
            results["factory_address"] = factory_address
            print(f"✓ Factory address: {factory_address}")
        except Exception as e:
            results["factory_address"] = None
            print(f"✗ Could not get factory: {e}")
        
        # Test 3: Get price quotes for different token pairs
        test_pairs = [
            (BASE_TOKENS["WETH"], BASE_TOKENS["USDC"], 18, 6, "WETH/USDC"),
            (BASE_TOKENS["WETH"], BASE_TOKENS["DAI"], 18, 18, "WETH/DAI"),
            (BASE_TOKENS["WETH"], BASE_TOKENS["USDT"], 18, 6, "WETH/USDT"),
            (BASE_TOKENS["WETH"], BASE_TOKENS["cbETH"], 18, 18, "WETH/cbETH"),
        ]
        
        for token_a, token_b, decimals_a, decimals_b, pair_name in test_pairs:
            try:
                # Get price for 1 unit of token_a
                amount_in = 10 ** decimals_a
                path = [token_a, token_b]
                
                # Call getAmountsOut
                amounts_out = router.functions.getAmountsOut(amount_in, path).call()
                amount_out = amounts_out[-1]  # Last amount is output
                
                # Calculate price
                price = Decimal(amount_out) / Decimal(10 ** decimals_b)
                
                # Get token symbols
                symbol_a = get_token_symbol(w3, token_a)
                symbol_b = get_token_symbol(w3, token_b)
                
                results["prices"][pair_name] = {
                    "token_a": symbol_a,
                    "token_b": symbol_b,
                    "amount_in": str(amount_in),
                    "amount_out": str(amount_out),
                    "price": str(price),
                    "decimals_a": decimals_a,
                    "decimals_b": decimals_b,
                }
                
                print(f"✓ {pair_name}: 1 {symbol_a} = {price:.6f} {symbol_b}")
            
            except Exception as e:
                results["prices"][pair_name] = {
                    "error": str(e)
                }
                print(f"✗ {pair_name}: {e}")
        
        # Test 4: Get top liquidity pool
        try:
            # Try to get factory and find a pair
            if results.get("factory_address"):
                factory = w3.eth.contract(address=results["factory_address"], abi=FACTORY_ABI)
                
                # Get WETH/USDC pair
                pair_address = factory.functions.getPair(
                    BASE_TOKENS["WETH"], 
                    BASE_TOKENS["USDC"]
                ).call()
                
                if pair_address != "0x0000000000000000000000000000000000000000":
                    results["top_pool"] = {
                        "address": pair_address,
                        "pair": "WETH/USDC"
                    }
                    print(f"✓ Top pool (WETH/USDC): {pair_address}")
                    
                    # Get reserves
                    try:
                        pair = w3.eth.contract(address=pair_address, abi=PAIR_ABI)
                        reserves = pair.functions.getReserves().call()
                        token0 = pair.functions.token0().call()
                        token1 = pair.functions.token1().call()
                        
                        symbol0 = get_token_symbol(w3, token0)
                        symbol1 = get_token_symbol(w3, token1)
                        decimals0 = get_token_decimals(w3, token0)
                        decimals1 = get_token_decimals(w3, token1)
                        
                        reserve0 = Decimal(reserves[0]) / Decimal(10 ** decimals0)
                        reserve1 = Decimal(reserves[1]) / Decimal(10 ** decimals1)
                        
                        results["top_pool"]["reserves"] = {
                            "token0": symbol0,
                            "token1": symbol1,
                            "reserve0": str(reserve0),
                            "reserve1": str(reserve1),
                        }
                        
                        print(f"  Reserves: {reserve0:.2f} {symbol0} / {reserve1:.2f} {symbol1}")
                    
                    except Exception as e:
                        results["top_pool"]["reserves_error"] = str(e)
                        print(f"  ✗ Could not get reserves: {e}")
                else:
                    results["top_pool"] = {"error": "Pair not found"}
                    print(f"✗ WETH/USDC pair not found")
        
        except Exception as e:
            results["top_pool"] = {"error": str(e)}
            print(f"✗ Could not find top pool: {e}")
    
    except Exception as e:
        results["error"] = str(e)
        print(f"✗ Contract error: {e}")
    
    return results

def main():
    print("=== Base DEX Price Fetching Test ===")
    print(f"Testing {len([d for d in KNOWN_BASE_DEXES.values() if d['role'] == 'router'])} DEX routers")
    print(f"Using {len(BASE_RPCS)} RPC endpoints")
    
    # Try to connect to Base RPC
    w3 = None
    for rpc in BASE_RPCS:
        try:
            print(f"\nTrying RPC: {rpc}")
            w3 = Web3(Web3.HTTPProvider(rpc))
            if w3.is_connected():
                print(f"✓ Connected to {rpc}")
                print(f"  Chain ID: {w3.eth.chain_id}")
                print(f"  Latest block: {w3.eth.block_number}")
                break
            else:
                print(f"✗ Failed to connect")
        except Exception as e:
            print(f"✗ Error: {e}")
    
    if not w3 or not w3.is_connected():
        print("\n✗ Could not connect to any Base RPC")
        print("Please check RPC endpoints or network connectivity")
        return
    
    # Test each DEX router
    all_results = []
    for addr, info in KNOWN_BASE_DEXES.items():
        if info["role"] == "router":
            try:
                result = test_dex_router(w3, addr, info["protocol"])
                all_results.append(result)
            except Exception as e:
                print(f"\n✗ Error testing {addr}: {e}")
                all_results.append({
                    "protocol": info["protocol"],
                    "role": info["role"],
                    "address": addr,
                    "error": str(e)
                })
    
    # Summary
    print(f"\n{'='*60}")
    print("=== Price Summary ===")
    print(f"{'='*60}")
    
    successful = 0
    for result in all_results:
        if "error" not in result:
            # Check if we got any prices
            prices = result.get("prices", {})
            successful_prices = [p for p in prices.values() if "price" in p]
            
            if successful_prices:
                successful += 1
                print(f"\n{result['protocol']}:")
                for pair_name, price_info in prices.items():
                    if "price" in price_info:
                        print(f"  {pair_name}: 1 {price_info['token_a']} = {price_info['price']} {price_info['token_b']}")
            else:
                print(f"\n✗ {result['protocol']}: No prices fetched")
        else:
            print(f"\n✗ {result['protocol']}: {result['error']}")
    
    print(f"\nTotal: {len(all_results)} routers tested")
    print(f"Successful: {successful}")
    print(f"Failed: {len(all_results) - successful}")
    
    # Save results
    output_file = Path.home() / ".hermes" / "data" / "base_dex_prices.json"
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_file}")

if __name__ == "__main__":
    main()