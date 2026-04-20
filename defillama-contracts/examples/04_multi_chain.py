#!/usr/bin/env python3
"""
Example: Multi-chain operations.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts


def main():
    """Main example function."""
    print("=== DefiLlama Contracts Example: Multi-Chain Operations ===\n")
    
    # Initialize client
    client = DefiLlamaContracts()
    
    # Get all chains
    chains = client.get_all_chains()
    print(f"Total chains with deployed contracts: {len(chains)}")
    
    # Display chain statistics
    print("\n=== Chain Statistics ===")
    print("-" * 60)
    print(f"{'Chain':<15} {'Deployed':<10} {'Failed':<10} {'Total':<10} {'Success Rate':<15}")
    print("-" * 60)
    
    for chain in chains:
        stats = client.get_chain_stats(chain)
        deployed = stats.get('deployed', 0)
        failed = stats.get('failed', 0)
        total = stats.get('total', 0)
        success_rate = (deployed / total * 100) if total > 0 else 0
        
        print(f"{chain:<15} {deployed:<10} {failed:<10} {total:<10} {success_rate:.1f}%")
    
    print("-" * 60)
    
    # Get contracts from different chains
    print("\n=== Sample Contracts from Different Chains ===")
    
    sample_chains = ["Ethereum", "Binance", "Arbitrum", "Base", "Polygon", "Avalanche", "Optimism", "Fantom"]
    
    for chain in sample_chains:
        contracts = client.get_chain_contracts(chain, "deployed", limit=1)
        if contracts:
            contract = contracts[0]
            print(f"{chain}: {contract.address}")
    
    # Compare gas prices across chains
    print("\n=== Gas Price Comparison ===")
    print("(Note: Gas prices vary by network conditions)")
    
    # This would require implementing get_gas_price in RPCProvider
    # For now, just display chain info
    
    # Export contracts
    print("\n=== Export Example ===")
    
    # Export Ethereum contracts to JSON
    eth_contracts = client.export_contracts(chain="Ethereum", status="deployed", format="json")
    print(f"Exported {len(eth_contracts.split('\\n'))} lines of JSON for Ethereum contracts")
    
    # Export all contracts to CSV
    all_contracts = client.export_contracts(status="deployed", format="csv")
    lines = all_contracts.split('\\n')
    print(f"Exported {len(lines)} lines of CSV for all contracts")
    
    # Display first few lines of CSV
    print("\nFirst 5 lines of CSV export:")
    for line in lines[:5]:
        print(line)
    
    # Close client
    client.close()


if __name__ == "__main__":
    main()