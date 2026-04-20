#!/usr/bin/env python3
"""
Quick start script for DefiLlama Contracts Library.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts


def main():
    """Quick start demonstration."""
    print("=== DefiLlama Contracts Quick Start ===\n")
    
    # Initialize client
    print("1. Initializing client...")
    client = DefiLlamaContracts()
    
    # Get database summary
    print("\n2. Database Summary:")
    summary = client.get_summary()
    print(f"   Total contracts: {summary['total_contracts']}")
    print(f"   Deployed contracts: {summary['deployed_contracts']}")
    print(f"   Failed contracts: {summary['failed_contracts']}")
    print(f"   Total chains: {summary['total_chains']}")
    
    # Get chains with most contracts
    print("\n3. Top 10 chains by deployed contracts:")
    chains = client.get_all_chains()
    chain_stats = []
    
    for chain in chains:
        stats = client.get_chain_stats(chain)
        deployed = stats.get('deployed', 0)
        chain_stats.append((chain, deployed))
    
    # Sort by deployed contracts
    chain_stats.sort(key=lambda x: x[1], reverse=True)
    
    for i, (chain, deployed) in enumerate(chain_stats[:10]):
        print(f"   {i+1}. {chain}: {deployed} deployed")
    
    # Get sample contracts from Ethereum
    print("\n4. Sample contracts from Ethereum:")
    eth_contracts = client.get_chain_contracts("Ethereum", "deployed", limit=5)
    
    for i, contract in enumerate(eth_contracts):
        print(f"   {i+1}. {contract.address}")
    
    # Get specific contract info
    print("\n5. Specific contract info (UNI token):")
    uni_address = "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"
    contract = client.get_contract("Ethereum", uni_address)
    
    if contract:
        print(f"   Contract: {contract}")
        print(f"   Is contract: {contract.is_contract()}")
        
        # Try to call methods
        try:
            code = contract.get_code()
            print(f"   Code length: {len(code)} characters")
        except Exception as e:
            print(f"   Error getting code: {e}")
    
    # Export example
    print("\n6. Export example:")
    print("   Exporting Ethereum contracts to JSON...")
    json_data = client.export_contracts(chain="Ethereum", status="deployed", format="json")
    lines = json_data.split("\n")
    print(f"   Exported {len(lines)} lines of JSON")
    
    # Close client
    client.close()
    
    print("\n=== Quick Start Complete ===")
    print("\nNext steps:")
    print("1. Explore examples in the examples/ directory")
    print("2. Read the README.md for detailed documentation")
    print("3. Use the CLI tool: python -m defillama_contracts.cli --help")
    print("4. Import the library in your Python code:")
    print("   from defillama_contracts import DefiLlamaContracts")
    print("   client = DefiLlamaContracts()")


if __name__ == "__main__":
    main()