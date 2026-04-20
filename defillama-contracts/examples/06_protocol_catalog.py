#!/usr/bin/env python3
"""
Example: Using Protocol Catalog to interact with contracts.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts, ProtocolContract, catalog, registry
from defillama_contracts.protocols import ProtocolType, ContractRole


def example_list_protocols():
    """Example: List all known protocols."""
    print("=== Example: List Protocols ===\n")
    
    # Get all protocols
    protocols = registry.list_protocols()
    print(f"Total protocols: {len(protocols)}")
    
    # Get protocols by type
    dex_protocols = registry.get_protocols_by_type(ProtocolType.DEX)
    print(f"\nDEX Protocols ({len(dex_protocols)}):")
    for p in dex_protocols:
        print(f"  - {p.name} ({p.version})")
    
    # Get protocols by chain
    eth_protocols = registry.get_protocols_by_chain("Ethereum")
    print(f"\nEthereum Protocols ({len(eth_protocols)}):")
    for p in eth_protocols[:10]:
        print(f"  - {p.name} ({p.protocol_type.value})")


def example_list_templates():
    """Example: List all protocol templates."""
    print("\n=== Example: List Templates ===\n")
    
    templates = catalog.list_templates()
    print(f"Total templates: {len(templates)}")
    
    # Get templates by type
    dex_templates = catalog.get_templates_by_type(ProtocolType.DEX)
    print(f"\nDEX Templates ({len(dex_templates)}):")
    for t in dex_templates:
        print(f"  - {t.protocol_type.value}/{t.contract_role.value}: {len(t.methods)} methods")


def example_uniswap_v2_methods():
    """Example: Show Uniswap V2 Router methods."""
    print("\n=== Example: Uniswap V2 Router Methods ===\n")
    
    template = catalog.get_template("uniswap_v2_router")
    if template:
        print(f"Protocol: {template.protocol_type.value}")
        print(f"Role: {template.contract_role.value}")
        print(f"Methods: {len(template.methods)}")
        
        print(f"\nRead Methods:")
        for method in template.get_methods_by_category("read"):
            print(f"  - {method.name}: {method.description}")
        
        print(f"\nWrite Methods:")
        for method in template.get_methods_by_category("write"):
            print(f"  - {method.name}: {method.description}")
            if method.gas_estimate:
                print(f"    Gas: {method.gas_estimate:,}")


def example_uniswap_v2_swap():
    """Example: Swap on Uniswap V2."""
    print("\n=== Example: Uniswap V2 Swap ===\n")
    
    client = DefiLlamaContracts()
    
    # Get Uniswap V2 Router
    router_address = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    contract = client.get_contract("Ethereum", router_address)
    
    if contract:
        # Create protocol-aware contract
        router = ProtocolContract(contract, "uniswap_v2", "router")
        
        print(f"Contract: {router}")
        print(f"Protocol: {router.protocol_name}")
        print(f"Role: {router.role}")
        
        # Get protocol info
        info = router.get_contract_info()
        print(f"\nContract Info:")
        print(f"  Is Contract: {info['is_contract']}")
        if 'token' in info and info['token']:
            print(f"  Token Info:")
            for key, value in info['token'].items():
                print(f"    {key}: {value}")
        
        # Get available methods
        print(f"\nAvailable Methods:")
        for method in router.get_available_methods():
            icon = "R" if method.state_mutability in ["view", "pure"] else "W"
            print(f"  [{icon}] {method.name}: {method.description}")
        
        # Example: Get swap quote
        print(f"\nExample: Get Swap Quote")
        weth = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        path = [weth, usdc]
        
        # 1 WETH = 1e18 wei
        amount_in = 10**18
        
        try:
            quote = router.get_swap_quote(amount_in, path, is_exact_input=True)
            if quote:
                print(f"  Input: {amount_in} WETH")
                print(f"  Output: {quote['amount_out']} USDC")
                print(f"  Path: {quote['path']}")
        except Exception as e:
            print(f"  Quote failed: {e}")
        
        # Example: Get factory
        print(f"\nExample: Get Factory")
        try:
            factory = router.call_protocol_method("factory")
            print(f"  Factory: {factory}")
        except Exception as e:
            print(f"  Failed: {e}")
    
    client.close()


def example_curve_swap():
    """Example: Swap on Curve."""
    print("\n=== Example: Curve Swap ===\n")
    
    client = DefiLlamaContracts()
    
    # Get Curve 3pool
    pool_address = "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7"
    contract = client.get_contract("Ethereum", pool_address)
    
    if contract:
        # Create protocol-aware contract
        pool = ProtocolContract(contract, "curve", "router")
        
        print(f"Contract: {pool}")
        print(f"Protocol: {pool.protocol_name}")
        print(f"Role: {pool.role}")
        
        # Get available methods
        print(f"\nAvailable Methods:")
        for method in pool.get_available_methods():
            icon = "R" if method.state_mutability in ["view", "pure"] else "W"
            print(f"  [{icon}] {method.name}: {method.description}")
        
        # Example: Get pool info
        print(f"\nExample: Pool Info")
        try:
            # Get amplification coefficient
            a = pool.call_protocol_method("A")
            print(f"  Amplification (A): {a}")
            
            # Get fee
            fee = pool.call_protocol_method("fee")
            print(f"  Fee: {fee}")
            
            # Get balances
            print(f"  Balances:")
            for i in range(3):
                try:
                    balance = pool.call_protocol_method("balances", [i])
                    print(f"    Token {i}: {balance}")
                except Exception:
                    break
        except Exception as e:
            print(f"  Failed: {e}")
    
    client.close()


def example_aave_v3():
    """Example: Interact with Aave V3."""
    print("\n=== Example: Aave V3 Lending Pool ===\n")
    
    client = DefiLlamaContracts()
    
    # Get Aave V3 Pool
    pool_address = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
    contract = client.get_contract("Ethereum", pool_address)
    
    if contract:
        # Create protocol-aware contract
        pool = ProtocolContract(contract, "aave_v3", "lending_pool")
        
        print(f"Contract: {pool}")
        print(f"Protocol: {pool.protocol_name}")
        print(f"Role: {pool.role}")
        print(f"Type: {pool.protocol_type.value}")
        
        # Get available methods
        print(f"\nAvailable Methods:")
        for method in pool.get_available_methods():
            icon = "R" if method.state_mutability in ["view", "pure"] else "W"
            print(f"  [{icon}] {method.name}: {method.description}")
        
        # Example: Get user account data
        print(f"\nExample: User Account Data")
        test_address = "0x0000000000000000000000000000000000000001"
        try:
            account_data = pool.get_user_account_data(test_address)
            if account_data:
                print(f"  Health Factor: {account_data['healthFactor'] / 10**18:.2f}")
                print(f"  Total Collateral (ETH): {account_data['totalCollateralETH'] / 10**18:.2f}")
                print(f"  Total Debt (ETH): {account_data['totalDebtETH'] / 10**18:.2f}")
        except Exception as e:
            print(f"  Failed: {e}")
    
    client.close()


def example_chainlink_oracle():
    """Example: Get price from Chainlink oracle."""
    print("\n=== Example: Chainlink Oracle ===\n")
    
    client = DefiLlamaContracts()
    
    # Get ETH/USD Chainlink feed
    feed_address = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
    contract = client.get_contract("Ethereum", feed_address)
    
    if contract:
        # Create protocol-aware contract
        oracle = ProtocolContract(contract, "chainlink", "price_feed")
        
        print(f"Contract: {oracle}")
        print(f"Protocol: {oracle.protocol_name}")
        print(f"Role: {oracle.role}")
        
        # Get price
        print(f"\nExample: Get ETH/USD Price")
        try:
            price_data = oracle.get_price()
            if price_data:
                answer = price_data.get("answer", 0)
                decimals = price_data.get("decimals", 8)
                price = answer / (10 ** decimals)
                
                print(f"  Price: ${price:.2f}")
                print(f"  Decimals: {decimals}")
                print(f"  Updated: {price_data.get('updatedAt', 'N/A')}")
                print(f"  Description: {price_data.get('description', 'N/A')}")
        except Exception as e:
            print(f"  Failed: {e}")
    
    client.close()


def example_find_protocol_by_address():
    """Example: Find protocol for a contract address."""
    print("\n=== Example: Find Protocol by Address ===\n")
    
    # Uniswap V2 Router
    address = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    chain = "Ethereum"
    
    result = registry.find_protocol_by_address(address, chain)
    
    if result:
        name, protocol, role = result
        print(f"Address: {address}")
        print(f"Chain: {chain}")
        print(f"Protocol: {name} ({protocol.name})")
        print(f"Role: {role}")
        print(f"Type: {protocol.protocol_type.value}")
        
        # Get template methods
        template = registry.get_template_for_contract(name, role)
        if template:
            print(f"\nAvailable Methods ({len(template.methods)}):")
            for method in template.methods[:5]:
                print(f"  - {method.name}: {method.description}")
            if len(template.methods) > 5:
                print(f"  ... and {len(template.methods) - 5} more")
    else:
        print(f"No protocol found for {address} on {chain}")


def main():
    """Run all examples."""
    print("=== Protocol Catalog Examples ===\n")
    
    try:
        example_list_protocols()
        example_list_templates()
        example_uniswap_v2_methods()
        example_find_protocol_by_address()
        
        # These examples require actual contract calls
        # Uncomment to run (requires RPC access)
        # example_uniswap_v2_swap()
        # example_curve_swap()
        # example_aave_v3()
        # example_chainlink_oracle()
        
        print("\n=== Examples Complete ===")
    
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()