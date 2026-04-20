#!/usr/bin/env python3
"""
Test script for Protocol Catalog.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts, ProtocolContract, catalog, registry
from defillama_contracts.protocols import ProtocolType, ContractRole


def test_catalog():
    """Test protocol catalog."""
    print("=== Testing Protocol Catalog ===\n")
    
    # Test listing templates
    templates = catalog.list_templates()
    print(f"✓ Templates available: {len(templates)}")
    
    # Test getting template
    uniswap_router = catalog.get_template("uniswap_v2_router")
    print(f"✓ Uniswap V2 Router template: {len(uniswap_router.methods)} methods")
    
    # Test getting templates by type
    dex_templates = catalog.get_templates_by_type(ProtocolType.DEX)
    print(f"✓ DEX templates: {len(dex_templates)}")
    
    # Test getting templates by role
    router_templates = catalog.get_templates_by_role(ContractRole.ROUTER)
    print(f"✓ Router templates: {len(router_templates)}")
    
    print()


def test_registry():
    """Test protocol registry."""
    print("=== Testing Protocol Registry ===\n")
    
    # Test listing protocols
    protocols = registry.list_protocols()
    print(f"✓ Protocols registered: {len(protocols)}")
    
    # Test getting protocol
    uniswap_v2 = registry.get_protocol("uniswap_v2")
    print(f"✓ Uniswap V2: {uniswap_v2.name} v{uniswap_v2.version}")
    
    # Test getting protocols by type
    dex_protocols = registry.get_protocols_by_type(ProtocolType.DEX)
    print(f"✓ DEX protocols: {len(dex_protocols)}")
    
    # Test getting protocols by chain
    eth_protocols = registry.get_protocols_by_chain("Ethereum")
    print(f"✓ Ethereum protocols: {len(eth_protocols)}")
    
    # Test finding protocol by address
    result = registry.find_protocol_by_address(
        "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "Ethereum"
    )
    if result:
        name, protocol, role = result
        print(f"✓ Found protocol for Uniswap V2 Router: {name} ({role})")
    
    # Test getting template for contract
    template = registry.get_template_for_contract("uniswap_v2", "router")
    print(f"✓ Template for Uniswap V2 Router: {len(template.methods)} methods")
    
    print()


def test_protocol_contract():
    """Test protocol contract wrapper."""
    print("=== Testing Protocol Contract ===\n")
    
    # Test with mock contract
    class MockContract:
        def __init__(self, address, chain):
            self.address = address
            self.chain = MockChain(chain)
        
        def call(self, method, params):
            if method == "factory":
                return "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
            elif method == "WETH":
                return "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
            elif method == "name":
                return "Uniswap V2 Router"
            elif method == "symbol":
                return "UNI-V2"
            elif method == "decimals":
                return 18
            elif method == "totalSupply":
                return 10**18
            return None
        
        def is_contract(self):
            return True
    
    class MockChain:
        def __init__(self, name):
            self.name = name
    
    # Create mock contract
    mock_contract = MockContract(
        "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "Ethereum"
    )
    
    # Test protocol contract
    router = ProtocolContract(mock_contract, "uniswap_v2", "router")
    
    print(f"✓ Protocol contract created: {router}")
    print(f"✓ Protocol name: {router.protocol_name}")
    print(f"✓ Protocol type: {router.protocol_type}")
    print(f"✓ Contract role: {router.role}")
    
    # Test getting available methods
    methods = router.get_available_methods()
    print(f"✓ Available methods: {len(methods)}")
    
    # Test getting read methods
    read_methods = router.get_read_methods()
    print(f"✓ Read methods: {len(read_methods)}")
    
    # Test getting write methods
    write_methods = router.get_write_methods()
    print(f"✓ Write methods: {len(write_methods)}")
    
    # Test finding method
    factory_method = router.find_method("factory")
    print(f"✓ Found method: {factory_method.name}")
    
    # Test calling protocol method
    factory = router.call_protocol_method("factory")
    print(f"✓ Called factory: {factory}")
    
    # Test getting contract info
    info = router.get_contract_info()
    print(f"✓ Contract info: {len(info)} fields")
    
    print()


def test_protocol_types():
    """Test protocol type coverage."""
    print("=== Testing Protocol Type Coverage ===\n")
    
    # Count protocols by type
    type_counts = {}
    for protocol_type in ProtocolType:
        protocols = registry.get_protocols_by_type(protocol_type)
        type_counts[protocol_type.value] = len(protocols)
    
    print("Protocol counts by type:")
    for type_name, count in sorted(type_counts.items()):
        print(f"  {type_name:15s}: {count}")
    
    # Count templates by type
    template_counts = {}
    for protocol_type in ProtocolType:
        templates = catalog.get_templates_by_type(protocol_type)
        template_counts[protocol_type.value] = len(templates)
    
    print("\nTemplate counts by type:")
    for type_name, count in sorted(template_counts.items()):
        print(f"  {type_name:15s}: {count}")
    
    print()


def test_method_coverage():
    """Test method coverage across templates."""
    print("=== Testing Method Coverage ===\n")
    
    total_methods = 0
    total_read = 0
    total_write = 0
    
    for template_name in catalog.list_templates():
        template = catalog.get_template(template_name)
        methods = template.methods
        
        read_count = len([m for m in methods if m.category == "read"])
        write_count = len([m for m in methods if m.category == "write"])
        
        total_methods += len(methods)
        total_read += read_count
        total_write += write_count
    
    print(f"Total methods across all templates: {total_methods}")
    print(f"Total read methods: {total_read}")
    print(f"Total write methods: {total_write}")
    
    print()


def main():
    """Run all tests."""
    print("=== Protocol Catalog Tests ===\n")
    
    try:
        test_catalog()
        test_registry()
        test_protocol_contract()
        test_protocol_types()
        test_method_coverage()
        
        print("=== All Tests Passed ===")
    
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())