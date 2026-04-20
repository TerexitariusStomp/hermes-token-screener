#!/usr/bin/env python3
"""
Example: Batch contract calls.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts


def main():
    """Main example function."""
    print("=== DefiLlama Contracts Example: Batch Calls ===\n")
    
    # Initialize client
    client = DefiLlamaContracts()
    
    # Define batch calls
    calls = [
        {
            "chain": "Ethereum",
            "address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",  # UNI
            "method": "name",
            "params": []
        },
        {
            "chain": "Ethereum",
            "address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",  # UNI
            "method": "symbol",
            "params": []
        },
        {
            "chain": "Ethereum",
            "address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",  # UNI
            "method": "decimals",
            "params": []
        },
        {
            "chain": "Ethereum",
            "address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",  # UNI
            "method": "totalSupply",
            "params": []
        },
        {
            "chain": "Ethereum",
            "address": "0xC02aaA39b223FE8D0A5C4F27eAD9083C756Cc2",  # WETH
            "method": "name",
            "params": []
        },
        {
            "chain": "Ethereum",
            "address": "0xC02aaA39b223FE8D0A5C4F27eAD9083C756Cc2",  # WETH
            "method": "symbol",
            "params": []
        },
        {
            "chain": "Ethereum",
            "address": "0xC02aaA39b223FE8D0A5C4F27eAD9083C756Cc2",  # WETH
            "method": "decimals",
            "params": []
        },
        {
            "chain": "Ethereum",
            "address": "0xC02aaA39b223FE8D0A5C4F27eAD9083C756Cc2",  # WETH
            "method": "totalSupply",
            "params": []
        },
    ]
    
    print(f"Executing {len(calls)} batch calls...\n")
    
    # Execute batch calls
    results = client.batch_call(calls)
    
    # Display results
    print("=== Batch Call Results ===")
    print("-" * 80)
    print(f"{'Chain':<10} {'Address':<42} {'Method':<15} {'Result':<20}")
    print("-" * 80)
    
    for i, result in enumerate(results):
        if "error" in result:
            print(f"{calls[i]['chain']:<10} {calls[i]['address'][:10]}...{calls[i]['address'][-8:]:<42} {calls[i]['method']:<15} ERROR: {result['error']}")
        else:
            # Truncate long results
            result_str = str(result.get('result', 'N/A'))
            if len(result_str) > 20:
                result_str = result_str[:17] + "..."
            print(f"{result['chain']:<10} {result['address'][:10]}...{result['address'][-8:]:<42} {result['method']:<15} {result_str:<20}")
    
    print("-" * 80)
    print(f"Completed {len(results)} calls")
    
    # Close client
    client.close()


if __name__ == "__main__":
    main()