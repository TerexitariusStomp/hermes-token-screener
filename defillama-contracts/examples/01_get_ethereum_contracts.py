#!/usr/bin/env python3
"""
Example: Getting all contracts on Ethereum.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts


def main():
    """Main example function."""
    print("=== DefiLlama Contracts Example: Get Ethereum Contracts ===\n")
    
    # Initialize client
    client = DefiLlamaContracts()
    
    # Get all deployed contracts on Ethereum
    print("Fetching deployed contracts on Ethereum...")
    eth_contracts = client.get_chain_contracts("Ethereum", "deployed")
    
    print(f"Found {len(eth_contracts)} deployed contracts on Ethereum\n")
    
    # Display first 10 contracts
    print("First 10 contracts:")
    print("-" * 80)
    print(f"{'Address':<42} {'Status':<10} {'Provider':<15} {'Code Size':<10}")
    print("-" * 80)
    
    for i, contract in enumerate(eth_contracts[:10]):
        print(f"{contract.address:<42} {contract.verification_status:<10} {contract.provider or 'N/A':<15} {contract.code_size or 'N/A':<10}")
    
    print("-" * 80)
    print(f"Showing 10 of {len(eth_contracts)} contracts")
    
    # Get chain statistics
    print("\n=== Ethereum Chain Statistics ===")
    stats = client.get_chain_stats("Ethereum")
    for key, value in stats.items():
        print(f"{key}: {value}")
    
    # Close client
    client.close()


if __name__ == "__main__":
    main()