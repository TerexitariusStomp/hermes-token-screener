#!/usr/bin/env python3
"""
Example: Interact with ANY contract in the database.
Demonstrates the universal contract classification and interaction system.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts, ProtocolContract


def example_classify_any_contract():
    """Classify any contract and get interaction methods."""
    print("=== Classify Any Contract ===\n")
    
    client = DefiLlamaContracts()
    
    # Get some contracts from Ethereum
    contracts = client.get_chain_contracts("Ethereum", "deployed", limit=5)
    
    for contract_info in contracts:
        print(f"\nContract: {contract_info.address}")
        print(f"Chain: {contract_info.chain}")
        
        # Classify the contract
        classification = client.classify_contract(contract_info.chain, contract_info.address)
        
        if "error" in classification:
            print(f"  Error: {classification['error']}")
            continue
        
        print(f"  Type: {classification['suggested_protocol_type']}")
        print(f"  Role: {classification['suggested_role']}")
        print(f"  Template: {classification['suggested_template']}")
        print(f"  Confidence: {classification['confidence']:.2f}")
        print(f"  Bytecode Size: {classification['bytecode_size']} bytes")
        
        if classification.get("erc20_info"):
            erc20 = classification["erc20_info"]
            print(f"  Token: {erc20.get('name', 'N/A')} ({erc20.get('symbol', 'N/A')})")
            print(f"  Decimals: {erc20.get('decimals', 'N/A')}")
        
        # Show detected methods
        methods = classification.get("interaction_methods", [])
        if methods:
            print(f"  Methods ({len(methods)}):")
            for method in methods[:5]:
                icon = "R" if method.get("state_mutability") in ["view", "pure"] else "W"
                print(f"    [{icon}] {method['name']}")
            if len(methods) > 5:
                print(f"    ... and {len(methods) - 5} more")
    
    client.close()


def example_smart_contract_interaction():
    """Get a smart contract wrapper for any contract."""
    print("\n=== Smart Contract Interaction ===\n")
    
    client = DefiLlamaContracts()
    
    # Get a contract
    contracts = client.get_chain_contracts("Ethereum", "deployed", limit=3)
    
    for contract_info in contracts:
        print(f"\nContract: {contract_info.address}")
        
        # Get smart contract wrapper
        smart = client.get_smart_contract(contract_info.chain, contract_info.address)
        
        if smart:
            print(f"  Protocol: {smart.protocol_name or 'auto-detected'}")
            print(f"  Role: {smart.role or 'unknown'}")
            print(f"  Type: {smart.protocol_type}")
            
            # Get contract info
            info = smart.get_contract_info()
            
            if info.get("token"):
                token = info["token"]
                if token.get("name"):
                    print(f"  Token: {token['name']} ({token.get('symbol', '')})")
            
            if info.get("methods"):
                print(f"  Available methods: {len(info['methods'])}")
        
        print()
    
    client.close()


def example_interaction_guide():
    """Get a complete interaction guide for any contract."""
    print("\n=== Interaction Guide ===\n")
    
    client = DefiLlamaContracts()
    
    # Get contracts from different types
    contracts = client.get_chain_contracts("Ethereum", "deployed", limit=5)
    
    for contract_info in contracts:
        print(f"\n{'='*60}")
        print(f"Contract: {contract_info.address}")
        print(f"{'='*60}")
        
        guide = client.get_contract_interaction_guide(
            contract_info.chain,
            contract_info.address
        )
        
        if "error" in guide:
            print(f"Error: {guide['error']}")
            continue
        
        # Show contract info
        c = guide["contract"]
        print(f"Chain: {c['chain']}")
        print(f"Type: {c['type']}")
        print(f"Role: {c['role']}")
        print(f"Confidence: {c['confidence']:.2f}")
        
        # Show token info if available
        if guide.get("token_info"):
            token = guide["token_info"]
            print(f"\nToken Info:")
            print(f"  Name: {token.get('name', 'N/A')}")
            print(f"  Symbol: {token.get('symbol', 'N/A')}")
            print(f"  Decimals: {token.get('decimals', 'N/A')}")
        
        # Show read methods
        if guide["read_methods"]:
            print(f"\nRead Methods ({len(guide['read_methods'])}):")
            for method in guide["read_methods"][:5]:
                print(f"  - {method['name']}: {method.get('description', '')}")
        
        # Show write methods
        if guide["write_methods"]:
            print(f"\nWrite Methods ({len(guide['write_methods'])}):")
            for method in guide["write_methods"][:5]:
                gas = f" (~{method['gas_estimate']:,} gas)" if method.get('gas_estimate') else ""
                print(f"  - {method['name']}{gas}: {method.get('description', '')}")
        
        # Show example code
        if guide.get("example_code"):
            print(f"\nExample Code:")
            print(guide["example_code"][:500] + "..." if len(guide["example_code"]) > 500 else guide["example_code"])
    
    client.close()


def example_classify_all_on_chain():
    """Classify all contracts on a specific chain."""
    print("\n=== Classify All Contracts on Ethereum ===\n")
    
    client = DefiLlamaContracts()
    
    # Get all Ethereum contracts
    eth_contracts = client.get_chain_contracts("Ethereum", "deployed")
    print(f"Total Ethereum contracts: {len(eth_contracts)}")
    
    # Classify first 10
    print(f"\nClassifying first 10 contracts...")
    classifications = client.classify_all_contracts("Ethereum", limit=10)
    
    # Group by type
    type_counts = {}
    for c in classifications:
        if "error" not in c:
            proto_type = c.get("suggested_protocol_type", "unknown")
            type_counts[proto_type] = type_counts.get(proto_type, 0) + 1
    
    print(f"\nClassification Results:")
    for proto_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {proto_type:20s}: {count}")
    
    client.close()


def example_any_contract_can_be_called():
    """Demonstrate that ANY contract can be called."""
    print("\n=== Any Contract Can Be Called ===\n")
    
    client = DefiLlamaContracts()
    
    # Get any random contract
    contracts = client.get_chain_contracts("Ethereum", "deployed", limit=1)
    
    if contracts:
        contract_info = contracts[0]
        print(f"Contract: {contract_info.address}")
        print(f"Chain: {contract_info.chain}")
        
        # Get the contract
        contract = client.get_contract(contract_info.chain, contract_info.address)
        
        if contract:
            print(f"\nThis contract CAN be interacted with:")
            print(f"  - contract.call(method, params) - Call any method")
            print(f"  - contract.get_balance() - Get ETH balance")
            print(f"  - contract.get_code() - Get bytecode")
            print(f"  - contract.is_contract() - Check if it's a contract")
            
            # Try some basic calls
            print(f"\nBasic calls:")
            try:
                is_contract = contract.is_contract()
                print(f"  is_contract: {is_contract}")
            except Exception as e:
                print(f"  is_contract: Error - {e}")
            
            try:
                balance = contract.get_balance()
                print(f"  balance: {balance}")
            except Exception as e:
                print(f"  balance: Error - {e}")
            
            try:
                code = contract.get_code()
                print(f"  code length: {len(code) if code else 0}")
            except Exception as e:
                print(f"  code: Error - {e}")
            
            # Try common ERC20 methods
            print(f"\nTrying common methods:")
            for method in ["name", "symbol", "decimals", "totalSupply"]:
                try:
                    result = contract.call(method, [])
                    print(f"  {method}: {result}")
                except Exception as e:
                    print(f"  {method}: Not available ({type(e).__name__})")
    
    client.close()


def main():
    """Run all examples."""
    print("=== Universal Contract Interaction Examples ===\n")
    print("This demonstrates how to interact with ALL 1,308 contracts in the database.\n")
    
    try:
        example_any_contract_can_be_called()
        example_classify_any_contract()
        example_smart_contract_interaction()
        
        # These require RPC access
        # example_interaction_guide()
        # example_classify_all_on_chain()
        
        print("\n=== All Examples Complete ===")
        print("\nKey Takeaway:")
        print("  Every contract in the database can be interacted with using:")
        print("  1. client.get_contract(chain, address) - Basic contract object")
        print("  2. client.get_smart_contract(chain, address) - Smart wrapper with auto-detection")
        print("  3. client.classify_contract(chain, address) - Classification and method discovery")
        print("  4. client.get_contract_interaction_guide(chain, address) - Complete guide")
    
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()