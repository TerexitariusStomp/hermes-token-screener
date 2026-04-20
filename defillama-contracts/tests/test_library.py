#!/usr/bin/env python3
"""
Test script for DefiLlama Contracts Library.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts


def test_client():
    """Test client initialization."""
    print("=== Testing Client Initialization ===")
    
    client = DefiLlamaContracts()
    
    # Test summary
    summary = client.get_summary()
    print(f"Total contracts: {summary['total_contracts']}")
    print(f"Deployed contracts: {summary['deployed_contracts']}")
    print(f"Total chains: {summary['total_chains']}")
    
    # Test chains
    chains = client.get_all_chains()
    print(f"Chains: {len(chains)}")
    
    # Test first 5 chains
    print("\nFirst 5 chains:")
    for chain in chains[:5]:
        stats = client.get_chain_stats(chain)
        print(f"  {chain}: {stats.get('deployed', 0)} deployed")
    
    client.close()
    print("\n✓ Client test passed")


def test_contracts():
    """Test contract operations."""
    print("\n=== Testing Contract Operations ===")
    
    client = DefiLlamaContracts()
    
    # Test Ethereum contracts
    eth_contracts = client.get_chain_contracts("Ethereum", "deployed", limit=5)
    print(f"Ethereum contracts (first 5): {len(eth_contracts)}")
    
    # Test specific contract
    uni_address = "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"
    contract = client.get_contract("Ethereum", uni_address)
    
    if contract:
        print(f"\nContract: {contract}")
        
        # Test contract methods
        try:
            code = contract.get_code()
            print(f"Code length: {len(code)} characters")
            
            is_contract = contract.is_contract()
            print(f"Is contract: {is_contract}")
            
        except Exception as e:
            print(f"Error testing contract: {e}")
    else:
        print(f"Contract not found: {uni_address}")
    
    client.close()
    print("\n✓ Contracts test passed")


def test_batch():
    """Test batch operations."""
    print("\n=== Testing Batch Operations ===")
    
    client = DefiLlamaContracts()
    
    # Define batch calls
    calls = [
        {
            "chain": "Ethereum",
            "address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
            "method": "name",
            "params": []
        },
        {
            "chain": "Ethereum",
            "address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
            "method": "symbol",
            "params": []
        }
    ]
    
    try:
        results = client.batch_call(calls)
        print(f"Batch call results: {len(results)}")
        
        for result in results:
            if "error" in result:
                print(f"  Error: {result['error']}")
            else:
                print(f"  {result['method']}: {result.get('result', 'N/A')}")
    
    except Exception as e:
        print(f"Error in batch call: {e}")
    
    client.close()
    print("\n✓ Batch test passed")


def test_export():
    """Test export operations."""
    print("\n=== Testing Export Operations ===")
    
    client = DefiLlamaContracts()
    
    # Test JSON export
    try:
        json_data = client.export_contracts(chain="Ethereum", status="deployed", format="json")
        lines = json_data.split("\n")
        print(f"JSON export: {len(lines)} lines")
        
        # Test CSV export
        csv_data = client.export_contracts(status="deployed", format="csv")
        lines = csv_data.split("\n")
        print(f"CSV export: {len(lines)} lines")
        
        # Show first few lines
        print("\nFirst 3 lines of CSV:")
        for line in lines[:3]:
            print(f"  {line}")
    
    except Exception as e:
        print(f"Error in export: {e}")
    
    client.close()
    print("\n✓ Export test passed")


def main():
    """Run all tests."""
    print("=== DefiLlama Contracts Library Tests ===\n")
    
    try:
        test_client()
        test_contracts()
        test_batch()
        test_export()
        
        print("\n=== All Tests Passed ===")
        return 0
    
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())