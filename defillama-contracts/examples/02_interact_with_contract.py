#!/usr/bin/env python3
"""
Example: Interacting with a specific contract.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts


def main():
    """Main example function."""
    print("=== DefiLlama Contracts Example: Interact with UNI Token ===\n")
    
    # Initialize client
    client = DefiLlamaContracts()
    
    # UNI token contract on Ethereum
    uni_address = "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"
    
    print(f"Getting contract: Ethereum:{uni_address}")
    contract = client.get_contract("Ethereum", uni_address)
    
    if not contract:
        print("Contract not found or not deployed")
        return
    
    print(f"Contract: {contract}")
    
    # Call contract methods
    print("\n=== Calling Contract Methods ===")
    
    try:
        # Get token name
        name = contract.call("name", [])
        print(f"Token name: {name}")
    except Exception as e:
        print(f"Error getting name: {e}")
    
    try:
        # Get token symbol
        symbol = contract.call("symbol", [])
        print(f"Token symbol: {symbol}")
    except Exception as e:
        print(f"Error getting symbol: {e}")
    
    try:
        # Get token decimals
        decimals = contract.call("decimals", [])
        print(f"Token decimals: {decimals}")
    except Exception as e:
        print(f"Error getting decimals: {e}")
    
    try:
        # Get total supply
        total_supply = contract.call("totalSupply", [])
        print(f"Total supply: {total_supply}")
    except Exception as e:
        print(f"Error getting total supply: {e}")
    
    try:
        # Get balance of a specific address
        # Example: Uniswap Treasury address
        treasury_address = "0x1a9C8182C09F50C8318d769245beA52c32BE35BC"
        balance = contract.call("balanceOf", [treasury_address])
        print(f"Balance of {treasury_address}: {balance}")
    except Exception as e:
        print(f"Error getting balance: {e}")
    
    # Get contract code
    print("\n=== Contract Information ===")
    code = contract.get_code()
    print(f"Code length: {len(code)} characters")
    
    # Check if it's a proxy contract
    implementation = contract.get_implementation()
    if implementation:
        print(f"Proxy implementation: {implementation}")
    else:
        print("Not a proxy contract")
    
    # Close client
    client.close()


if __name__ == "__main__":
    main()