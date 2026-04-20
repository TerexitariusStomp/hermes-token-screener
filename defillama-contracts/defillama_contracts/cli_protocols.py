#!/usr/bin/env python3
"""
CLI commands for protocol catalog exploration.
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts, ProtocolContract, catalog, registry
from defillama_contracts.protocols import ProtocolType, ContractRole


def cmd_protocols_list(args):
    """List all known protocols."""
    print("=== Known DeFi Protocols ===\n")
    
    protocols = registry.list_protocols()
    
    if args.type:
        protocol_type = ProtocolType(args.type)
        protocols = [p for p in protocols if registry.get_protocol(p).protocol_type == protocol_type]
    
    if args.chain:
        protocols = [p for p in protocols if args.chain in registry.get_protocol(p).chains]
    
    for name in sorted(protocols):
        protocol = registry.get_protocol(name)
        chains_str = ", ".join(protocol.chains[:3])
        if len(protocol.chains) > 3:
            chains_str += f" +{len(protocol.chains)-3} more"
        
        print(f"  {name:20s} {protocol.protocol_type.value:15s} v{protocol.version:6s} {chains_str}")
    
    print(f"\nTotal: {len(protocols)} protocols")


def cmd_protocols_info(args):
    """Show detailed protocol information."""
    protocol = registry.get_protocol(args.protocol)
    
    if not protocol:
        print(f"Protocol '{args.protocol}' not found")
        return
    
    print(f"=== {protocol.name} ===\n")
    print(f"Type:    {protocol.protocol_type.value}")
    print(f"Version: {protocol.version}")
    print(f"Chains:  {', '.join(protocol.chains)}")
    
    if protocol.website:
        print(f"Website: {protocol.website}")
    if protocol.docs:
        print(f"Docs:    {protocol.docs}")
    if protocol.github:
        print(f"GitHub:  {protocol.github}")
    
    print(f"\nContracts:")
    for role, addresses in protocol.contracts.items():
        print(f"\n  {role}:")
        for addr in addresses:
            print(f"    {addr}")
    
    print(f"\nTemplates:")
    for role, template_name in protocol.templates.items():
        print(f"  {role}: {template_name}")
    
    # Show methods for each template
    if args.methods:
        print(f"\nAvailable Methods:")
        for role, template_name in protocol.templates.items():
            template = catalog.get_template(template_name)
            if template:
                print(f"\n  {role} ({template_name}):")
                for method in template.methods:
                    print(f"    {method.name:30s} {method.signature}")
                    if method.description:
                        print(f"      {method.description}")


def cmd_protocols_templates(args):
    """List all protocol templates."""
    print("=== Protocol Templates ===\n")
    
    templates = catalog.list_templates()
    
    if args.type:
        protocol_type = ProtocolType(args.type)
        templates = [t for t in templates if catalog.get_template(t).protocol_type == protocol_type]
    
    for name in sorted(templates):
        template = catalog.get_template(name)
        methods_count = len(template.methods)
        
        print(f"  {name:30s} {template.protocol_type.value:15s} {template.contract_role.value:20s} {methods_count} methods")
    
    print(f"\nTotal: {len(templates)} templates")


def cmd_protocols_methods(args):
    """Show methods for a template."""
    template = catalog.get_template(args.template)
    
    if not template:
        print(f"Template '{args.template}' not found")
        return
    
    print(f"=== {args.template} Methods ===\n")
    print(f"Protocol Type: {template.protocol_type.value}")
    print(f"Contract Role: {template.contract_role.value}")
    
    if template.standard_interfaces:
        print(f"Interfaces: {', '.join(template.standard_interfaces)}")
    
    print(f"\nMethods ({len(template.methods)}):\n")
    
    for method in template.methods:
        mutability_icon = {
            "view": "R",
            "pure": "R",
            "nonpayable": "W",
            "payable": "W$"
        }.get(method.state_mutability, "?")
        
        print(f"  [{mutability_icon}] {method.name}")
        print(f"      Signature: {method.signature}")
        print(f"      Description: {method.description or 'N/A'}")
        print(f"      Category: {method.category}")
        
        if method.gas_estimate:
            print(f"      Gas Estimate: {method.gas_estimate:,}")
        
        if method.inputs:
            print(f"      Inputs:")
            for inp in method.inputs:
                print(f"        - {inp['name']}: {inp['type']}")
        
        if method.outputs:
            print(f"      Outputs:")
            for out in method.outputs:
                print(f"        - {out['type']}")
        
        print()


def cmd_protocols_search(args):
    """Search for protocols containing a contract address."""
    result = registry.find_protocol_by_address(args.address, args.chain)
    
    if result:
        name, protocol, role = result
        print(f"Found: {name} ({protocol.name})")
        print(f"Role:  {role}")
        print(f"Type:  {protocol.protocol_type.value}")
        
        # Show available methods
        template = registry.get_template_for_contract(name, role)
        if template:
            print(f"\nAvailable Methods ({len(template.methods)}):")
            for method in template.methods:
                icon = "R" if method.state_mutability in ["view", "pure"] else "W"
                print(f"  [{icon}] {method.name:30s} {method.description or ''}")
    else:
        print(f"No protocol found for {args.address} on {args.chain}")


def cmd_protocols_verify(args):
    """Verify contract matches expected protocol."""
    client = DefiLlamaContracts()
    contract = client.get_contract(args.chain, args.address)
    
    if not contract:
        print(f"Contract not found: {args.address} on {args.chain}")
        client.close()
        return
    
    protocol_contract = ProtocolContract(contract)
    
    print(f"=== Contract Verification ===\n")
    print(f"Address: {args.address}")
    print(f"Chain:   {args.chain}")
    print(f"Is Contract: {contract.is_contract()}")
    
    if protocol_contract.protocol:
        print(f"\nDetected Protocol:")
        print(f"  Name: {protocol_contract.protocol.name}")
        print(f"  Type: {protocol_contract.protocol_type.value}")
        print(f"  Role: {protocol_contract.role}")
        
        # Try to call common methods
        print(f"\nVerification Checks:")
        
        if protocol_contract.role == "pair":
            try:
                token0 = protocol_contract.call_protocol_method("token0")
                token1 = protocol_contract.call_protocol_method("token1")
                reserves = protocol_contract.call_protocol_method("getReserves")
                
                print(f"  [OK] token0: {token0}")
                print(f"  [OK] token1: {token1}")
                print(f"  [OK] reserves: {reserves[0]}, {reserves[1]}")
            except Exception as e:
                print(f"  [FAIL] Pair verification failed: {e}")
        
        elif protocol_contract.role == "router":
            try:
                factory = protocol_contract.call_protocol_method("factory")
                print(f"  [OK] factory: {factory}")
            except Exception as e:
                print(f"  [FAIL] Router verification failed: {e}")
        
        elif protocol_contract.role == "factory":
            try:
                pairs_length = protocol_contract.call_protocol_method("allPairsLength")
                print(f"  [OK] allPairsLength: {pairs_length}")
            except Exception as e:
                print(f"  [FAIL] Factory verification failed: {e}")
        
        elif protocol_contract.role == "lending_pool":
            try:
                # Try to get reserve data for USDC
                usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
                reserve_data = protocol_contract.call_protocol_method("getReserveData", [usdc])
                print(f"  [OK] getReserveData: {len(reserve_data)} fields")
            except Exception as e:
                print(f"  [FAIL] Lending pool verification failed: {e}")
        
        elif protocol_contract.role == "price_feed":
            try:
                price_data = protocol_contract.get_price()
                if price_data:
                    answer = price_data.get("answer", 0)
                    decimals = price_data.get("decimals", 8)
                    price = answer / (10 ** decimals)
                    print(f"  [OK] Price: ${price:.2f}")
                    print(f"  [OK] Updated: {price_data.get('updatedAt', 'N/A')}")
            except Exception as e:
                print(f"  [FAIL] Oracle verification failed: {e}")
    
    else:
        print(f"\nNo protocol detected for this contract")
        
        # Try basic ERC20 checks
        print(f"\nBasic ERC20 Checks:")
        for method_name in ["name", "symbol", "decimals", "totalSupply"]:
            try:
                result = contract.call(method_name, [])
                print(f"  [OK] {method_name}: {result}")
            except Exception:
                print(f"  [SKIP] {method_name}: not available")
    
    client.close()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Protocol Catalog CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # List protocols
    list_parser = subparsers.add_parser("list", help="List all protocols")
    list_parser.add_argument("--type", help="Filter by protocol type")
    list_parser.add_argument("--chain", help="Filter by chain")
    
    # Protocol info
    info_parser = subparsers.add_parser("info", help="Show protocol details")
    info_parser.add_argument("protocol", help="Protocol name")
    info_parser.add_argument("--methods", action="store_true", help="Show methods")
    
    # List templates
    templates_parser = subparsers.add_parser("templates", help="List all templates")
    templates_parser.add_argument("--type", help="Filter by protocol type")
    
    # Show methods
    methods_parser = subparsers.add_parser("methods", help="Show template methods")
    methods_parser.add_argument("template", help="Template name")
    
    # Search by address
    search_parser = subparsers.add_parser("search", help="Find protocol by address")
    search_parser.add_argument("address", help="Contract address")
    search_parser.add_argument("--chain", required=True, help="Chain name")
    
    # Verify contract
    verify_parser = subparsers.add_parser("verify", help="Verify contract protocol")
    verify_parser.add_argument("address", help="Contract address")
    verify_parser.add_argument("--chain", required=True, help="Chain name")
    
    args = parser.parse_args()
    
    if args.command == "list":
        cmd_protocols_list(args)
    elif args.command == "info":
        cmd_protocols_info(args)
    elif args.command == "templates":
        cmd_protocols_templates(args)
    elif args.command == "methods":
        cmd_protocols_methods(args)
    elif args.command == "search":
        cmd_protocols_search(args)
    elif args.command == "verify":
        cmd_protocols_verify(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()