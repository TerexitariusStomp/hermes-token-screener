#!/usr/bin/env python3
"""
Example: DEX contract interactions.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts


def main():
    """Main example function."""
    print("=== DefiLlama Contracts Example: DEX Interactions ===\n")
    
    # Initialize client
    client = DefiLlamaContracts()
    
    # Example: Uniswap V2 Router on Ethereum
    print("=== Uniswap V2 Router ===")
    
    # Uniswap V2 Router address
    uniswap_router = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    
    contract = client.get_contract("Ethereum", uniswap_router)
    if contract:
        print(f"Contract: {contract}")
        
        try:
            # Get factory address
            factory = contract.call("factory", [])
            print(f"Factory: {factory}")
        except Exception as e:
            print(f"Error getting factory: {e}")
        
        try:
            # Get WETH address
            weth = contract.call("WETH", [])
            print(f"WETH: {weth}")
        except Exception as e:
            print(f"Error getting WETH: {e}")
        
        # Example: Get amount out for a swap
        try:
            # 1 ETH -> USDC
            amount_in = 10**18  # 1 ETH
            reserves = [1000 * 10**18, 2000000 * 10**6]  # Example reserves
            
            # Note: This would need proper reserves from the pair contract
            # For demonstration, we'll just show the method signature
            print(f"\nTo calculate swap amounts, you would call:")
            print(f"  getAmountOut({amount_in}, {reserves[0]}, {reserves[1]})")
            
        except Exception as e:
            print(f"Error calculating swap: {e}")
    
    # Example: Uniswap V2 Factory
    print("\n=== Uniswap V2 Factory ===")
    
    # Uniswap V2 Factory address
    uniswap_factory = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
    
    contract = client.get_contract("Ethereum", uniswap_factory)
    if contract:
        print(f"Contract: {contract}")
        
        try:
            # Get all pairs length
            all_pairs_length = contract.call("allPairsLength", [])
            print(f"Total pairs: {all_pairs_length}")
        except Exception as e:
            print(f"Error getting pairs length: {e}")
        
        try:
            # Get first pair
            if all_pairs_length and int(all_pairs_length) > 0:
                first_pair = contract.call("allPairs", [0])
                print(f"First pair: {first_pair}")
        except Exception as e:
            print(f"Error getting first pair: {e}")
    
    # Example: Get pair for specific tokens
    print("\n=== Get Pair for Tokens ===")
    
    # Token addresses
    weth = "0xC02aaA39b223FE8D0A5C4F27eAD9083C756Cc2"
    usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    
    if contract:
        try:
            # Get pair for WETH/USDC
            pair = contract.call("getPair", [weth, usdc])
            print(f"WETH/USDC pair: {pair}")
            
            # Get pair contract
            pair_contract = client.get_contract("Ethereum", pair)
            if pair_contract:
                print(f"Pair contract: {pair_contract}")
                
                try:
                    # Get token0 and token1
                    token0 = pair_contract.call("token0", [])
                    token1 = pair_contract.call("token1", [])
                    print(f"Token0: {token0}")
                    print(f"Token1: {token1}")
                    
                    # Get reserves
                    reserves = pair_contract.call("getReserves", [])
                    print(f"Reserves: {reserves}")
                    
                except Exception as e:
                    print(f"Error getting pair info: {e}")
                    
        except Exception as e:
            print(f"Error getting pair: {e}")
    
    # Example: Multi-chain DEXes
    print("\n=== Multi-Chain DEXes ===")
    
    # PancakeSwap on Binance
    print("\nPancakeSwap (Binance):")
    pancake_router = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
    contract = client.get_contract("Binance", pancake_router)
    if contract:
        print(f"  Router: {contract}")
    
    # TraderJoe on Avalanche
    print("\nTraderJoe (Avalanche):")
    traderjoe_router = "0x60aE616a2155Ee3d9A68541Ba4544862310933d4"
    contract = client.get_contract("Avalanche", traderjoe_router)
    if contract:
        print(f"  Router: {contract}")
    
    # SushiSwap on Ethereum
    print("\nSushiSwap (Ethereum):")
    sushi_router = "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F"
    contract = client.get_contract("Ethereum", sushi_router)
    if contract:
        print(f"  Router: {contract}")
    
    # Close client
    client.close()


if __name__ == "__main__":
    main()