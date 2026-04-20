#!/usr/bin/env python3
"""
Command-line interface for DefiLlama Contracts Library.
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from defillama_contracts import DefiLlamaContracts


def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description="DefiLlama Contracts CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all chains
  python -m defillama_contracts.cli chains
  
  # Get contracts on Ethereum
  python -m defillama_contracts.cli contracts --chain Ethereum
  
  # Get specific contract info
  python -m defillama_contracts.cli info --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984
  
  # Call contract method
  python -m defillama_contracts.cli call --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984 --method name
  
  # Export contracts
  python -m defillama_contracts.cli export --chain Ethereum --format json
  
  # Show statistics
  python -m defillama_contracts.cli stats
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Chains command
    chains_parser = subparsers.add_parser("chains", help="List all chains")
    chains_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # Contracts command
    contracts_parser = subparsers.add_parser("contracts", help="Get contracts")
    contracts_parser.add_argument("--chain", required=True, help="Chain name")
    contracts_parser.add_argument(
        "--status",
        choices=["deployed", "failed", "all"],
        default="deployed",
        help="Contract status",
    )
    contracts_parser.add_argument(
        "--limit", type=int, help="Maximum number of contracts"
    )
    contracts_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # Info command
    info_parser = subparsers.add_parser("info", help="Get contract information")
    info_parser.add_argument("--chain", required=True, help="Chain name")
    info_parser.add_argument("--address", required=True, help="Contract address")
    info_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # Call command
    call_parser = subparsers.add_parser("call", help="Call contract method")
    call_parser.add_argument("--chain", required=True, help="Chain name")
    call_parser.add_argument("--address", required=True, help="Contract address")
    call_parser.add_argument("--method", required=True, help="Method name")
    call_parser.add_argument("--params", nargs="*", help="Method parameters")
    call_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # Export command
    export_parser = subparsers.add_parser("export", help="Export contracts")
    export_parser.add_argument("--chain", help="Chain name")
    export_parser.add_argument(
        "--status",
        choices=["deployed", "failed", "all"],
        default="deployed",
        help="Contract status",
    )
    export_parser.add_argument(
        "--format", choices=["json", "csv", "sql"], default="json", help="Export format"
    )
    export_parser.add_argument("--output", help="Output file path")

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show statistics")
    stats_parser.add_argument("--chain", help="Chain name")
    stats_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # Search command
    search_parser = subparsers.add_parser("search", help="Search contracts")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--chain", help="Chain name")
    search_parser.add_argument(
        "--status",
        choices=["deployed", "failed", "all"],
        default="deployed",
        help="Contract status",
    )
    search_parser.add_argument("--limit", type=int, default=50, help="Maximum results")
    search_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # Classify command
    classify_parser = subparsers.add_parser(
        "classify", help="Classify a contract by probing on-chain"
    )
    classify_parser.add_argument("--chain", required=True, help="Chain name")
    classify_parser.add_argument("--address", required=True, help="Contract address")
    classify_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # Guide command
    guide_parser = subparsers.add_parser(
        "guide", help="Get interaction guide for any contract"
    )
    guide_parser.add_argument("--chain", required=True, help="Chain name")
    guide_parser.add_argument("--address", required=True, help="Contract address")
    guide_parser.add_argument("--code", action="store_true", help="Show example code")
    guide_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # Smart command
    smart_parser = subparsers.add_parser(
        "smart", help="Get smart contract with auto-detected methods"
    )
    smart_parser.add_argument("--chain", required=True, help="Chain name")
    smart_parser.add_argument("--address", required=True, help="Contract address")

    # Price command
    price_parser = subparsers.add_parser(
        "price", help="Fetch prices from DEX contracts"
    )
    price_parser.add_argument("--chain", required=True, help="Chain name")
    price_parser.add_argument("--dex", help="Specific DEX address (optional)")
    price_parser.add_argument("--token-a", help="Token A address (default: WETH)")
    price_parser.add_argument("--token-b", help="Token B address (default: USDC)")
    price_parser.add_argument(
        "--amount", type=float, default=1.0, help="Amount of token A to price"
    )
    price_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # DEX command
    dex_parser = subparsers.add_parser("dex", help="List DEX contracts on a chain")
    dex_parser.add_argument("--chain", required=True, help="Chain name")
    dex_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum number to show"
    )
    dex_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # DB command
    db_parser = subparsers.add_parser("db", help="Show database information")
    db_parser.add_argument("--info", action="store_true", help="Show database info")
    db_parser.add_argument(
        "--tables", action="store_true", help="Show table structures"
    )
    db_parser.add_argument("--query", help="Execute custom SQL query")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Initialize client
    client = DefiLlamaContracts()

    try:
        if args.command == "chains":
            chains = client.get_all_chains()
            if args.format == "json":
                print(json.dumps(chains, indent=2))
            else:
                print(f"Total chains: {len(chains)}")
                for chain in chains:
                    print(f"  {chain}")

        elif args.command == "contracts":
            contracts = client.get_chain_contracts(args.chain, args.status, args.limit)
            if args.format == "json":
                print(json.dumps([vars(c) for c in contracts], indent=2))
            else:
                print(f"Found {len(contracts)} contracts on {args.chain}")
                print("-" * 80)
                print(
                    f"{'Address':<42} {'Status':<10} {'Provider':<15} {'Code Size':<10}"
                )
                print("-" * 80)
                for contract in contracts:
                    print(
                        f"{contract.address:<42} {contract.verification_status:<10} {contract.provider or 'N/A':<15} {contract.code_size or 'N/A':<10}"
                    )

        elif args.command == "info":
            contract = client.get_contract(args.chain, args.address)
            if contract:
                info = {
                    "chain": args.chain,
                    "address": args.address,
                    "is_contract": contract.is_contract(),
                    "code_length": len(contract.get_code()),
                    "implementation": contract.get_implementation(),
                }

                if args.format == "json":
                    print(json.dumps(info, indent=2))
                else:
                    print(f"Contract Information:")
                    print(f"  Chain: {info['chain']}")
                    print(f"  Address: {info['address']}")
                    print(f"  Is Contract: {info['is_contract']}")
                    print(f"  Code Length: {info['code_length']} bytes")
                    if info["implementation"]:
                        print(f"  Implementation: {info['implementation']}")
            else:
                print(f"Contract not found: {args.chain}:{args.address}")

        elif args.command == "call":
            contract = client.get_contract(args.chain, args.address)
            if contract:
                try:
                    params = args.params or []
                    result = contract.call(args.method, params)

                    if args.format == "json":
                        print(json.dumps({"result": result}, indent=2))
                    else:
                        print(f"Method: {args.method}")
                        print(f"Result: {result}")
                except Exception as e:
                    print(f"Error calling method: {e}")
            else:
                print(f"Contract not found: {args.chain}:{args.address}")

        elif args.command == "export":
            data = client.export_contracts(args.chain, args.status, args.format)

            if args.output:
                with open(args.output, "w") as f:
                    f.write(data)
                print(f"Exported to {args.output}")
            else:
                print(data)

        elif args.command == "stats":
            if args.chain:
                stats = client.get_chain_stats(args.chain)
                if args.format == "json":
                    print(json.dumps(stats, indent=2))
                else:
                    print(f"Statistics for {args.chain}:")
                    for key, value in stats.items():
                        print(f"  {key}: {value}")
            else:
                summary = client.get_summary()
                if args.format == "json":
                    print(json.dumps(summary, indent=2))
                else:
                    print("Database Summary:")
                    print(f"  Total contracts: {summary['total_contracts']}")
                    print(f"  Deployed contracts: {summary['deployed_contracts']}")
                    print(f"  Failed contracts: {summary['failed_contracts']}")
                    print(f"  Total chains: {summary['total_chains']}")
                    print(f"  Chains: {', '.join(summary['chains'][:10])}...")

        elif args.command == "search":
            contracts = client.search_contracts(
                args.query, args.chain, args.status, args.limit
            )
            if args.format == "json":
                print(json.dumps([vars(c) for c in contracts], indent=2))
            else:
                print(f"Found {len(contracts)} contracts matching '{args.query}'")
                print("-" * 80)
                print(f"{'Chain':<15} {'Address':<42} {'Status':<10}")
                print("-" * 80)
                for contract in contracts:
                    print(
                        f"{contract.chain:<15} {contract.address:<42} {contract.verification_status:<10}"
                    )

        elif args.command == "classify":
            result = client.classify_contract(args.chain, args.address)
            if args.format == "json":
                print(json.dumps(result, indent=2, default=str))
            else:
                if "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    print(f"Contract Classification:")
                    print(f"  Address: {result['address']}")
                    print(f"  Chain: {result['chain']}")
                    print(f"  Type: {result['suggested_protocol_type']}")
                    print(f"  Role: {result['suggested_role']}")
                    print(f"  Template: {result['suggested_template']}")
                    print(f"  Confidence: {result['confidence']:.2f}")
                    print(f"  Bytecode: {result['bytecode_size']} bytes")
                    print(f"  Is Proxy: {result.get('is_proxy', False)}")

                    if result.get("erc20_info"):
                        erc20 = result["erc20_info"]
                        print(f"\nToken Info:")
                        for key, value in erc20.items():
                            print(f"  {key}: {value}")

                    if result.get("detected_categories"):
                        print(f"\nDetected Categories:")
                        for cat in result["detected_categories"]:
                            print(f"  - {cat}")

                    methods = result.get("interaction_methods", [])
                    if methods:
                        print(f"\nInteraction Methods ({len(methods)}):")
                        for method in methods:
                            icon = (
                                "R"
                                if method.get("state_mutability") in ["view", "pure"]
                                else "W"
                            )
                            source = method.get("source", "unknown")
                            print(f"  [{icon}] {method['name']:30s} ({source})")

        elif args.command == "guide":
            guide = client.get_contract_interaction_guide(args.chain, args.address)
            if args.format == "json":
                print(json.dumps(guide, indent=2, default=str))
            else:
                if "error" in guide:
                    print(f"Error: {guide['error']}")
                else:
                    c = guide["contract"]
                    print(f"Contract Interaction Guide:")
                    print(f"  Address: {c['address']}")
                    print(f"  Chain: {c['chain']}")
                    print(f"  Type: {c['type']}")
                    print(f"  Role: {c['role']}")
                    print(f"  Confidence: {c['confidence']:.2f}")

                    if guide.get("token_info"):
                        token = guide["token_info"]
                        print(
                            f"\nToken: {token.get('name', 'N/A')} ({token.get('symbol', 'N/A')})"
                        )
                        print(f"Decimals: {token.get('decimals', 'N/A')}")

                    if guide["read_methods"]:
                        print(f"\nRead Methods ({len(guide['read_methods'])}):")
                        for method in guide["read_methods"]:
                            desc = (
                                f" - {method['description']}"
                                if method.get("description")
                                else ""
                            )
                            print(f"  - {method['name']}{desc}")

                    if guide["write_methods"]:
                        print(f"\nWrite Methods ({len(guide['write_methods'])}):")
                        for method in guide["write_methods"]:
                            gas = (
                                f" (~{method['gas_estimate']:,} gas)"
                                if method.get("gas_estimate")
                                else ""
                            )
                            desc = (
                                f" - {method['description']}"
                                if method.get("description")
                                else ""
                            )
                            print(f"  - {method['name']}{gas}{desc}")

                    if args.code and guide.get("example_code"):
                        print(f"\nExample Code:")
                        print(guide["example_code"])

        elif args.command == "smart":
            smart = client.get_smart_contract(args.chain, args.address)
            if smart:
                info = smart.get_contract_info()
                print(f"Smart Contract:")
                print(f"  Address: {args.address}")
                print(f"  Chain: {args.chain}")
                print(f"  Protocol: {smart.protocol_name or 'auto-detected'}")
                print(f"  Role: {smart.role or 'unknown'}")
                print(f"  Type: {smart.protocol_type}")

                if info.get("token"):
                    token = info["token"]
                    if token.get("name"):
                        print(f"\nToken: {token['name']} ({token.get('symbol', '')})")

                if info.get("methods"):
                    print(f"\nAvailable Methods ({len(info['methods'])}):")
                    for method in info["methods"][:10]:
                        icon = (
                            "R"
                            if method.get("state_mutability") in ["view", "pure"]
                            else "W"
                        )
                        print(f"  [{icon}] {method['name']}")
                    if len(info["methods"]) > 10:
                        print(f"  ... and {len(info['methods']) - 10} more")
            else:
                print(f"Contract not found: {args.chain}:{args.address}")

        elif args.command == "price":
            # Import price fetching functionality
            from defillama_contracts.core.price_fetcher import PriceFetcher

            fetcher = PriceFetcher(client)

            # Default tokens for common chains
            default_tokens = {
                "Base": {
                    "WETH": "0x4200000000000000000000000000000000000006",
                    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                },
                "Ethereum": {
                    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                },
            }

            token_a = args.token_a
            token_b = args.token_b

            # Use defaults if not specified
            if not token_a and args.chain in default_tokens:
                token_a = default_tokens[args.chain].get("WETH")
            if not token_b and args.chain in default_tokens:
                token_b = default_tokens[args.chain].get("USDC")

            if not token_a or not token_b:
                print(
                    "Error: Could not determine token addresses. Use --token-a and --token-b"
                )
                return

            if args.dex:
                # Fetch from specific DEX
                result = fetcher.fetch_price(
                    chain=args.chain,
                    dex_address=args.dex,
                    token_a=token_a,
                    token_b=token_b,
                    amount=args.amount,
                )

                if args.format == "json":
                    print(json.dumps(result, indent=2, default=str))
                else:
                    if "error" in result:
                        print(f"Error: {result['error']}")
                    else:
                        print(f"Price from {result.get('protocol', 'DEX')}:")
                        print(
                            f"  {result['amount_in']} {result['token_a_symbol']} = {result['amount_out']} {result['token_b_symbol']}"
                        )
                        if result.get("pool_address"):
                            print(f"  Pool: {result['pool_address']}")
            else:
                # Fetch from all DEXes on chain
                results = fetcher.fetch_all_prices(
                    chain=args.chain,
                    token_a=token_a,
                    token_b=token_b,
                    amount=args.amount,
                )

                if args.format == "json":
                    print(json.dumps(results, indent=2, default=str))
                else:
                    print(f"Prices on {args.chain} ({len(results)} DEXes):")
                    print("-" * 80)
                    for r in results:
                        if "error" not in r:
                            print(
                                f"{r.get('protocol', 'Unknown'):20s}: 1 {r['token_a_symbol']} = {r['amount_out']} {r['token_b_symbol']}"
                            )
                        else:
                            print(
                                f"{r.get('protocol', 'Unknown'):20s}: Error - {r['error']}"
                            )

        elif args.command == "dex":
            # Get deployed contracts and classify to find DEXes
            contracts = client.get_chain_contracts(
                args.chain, "deployed", args.limit * 5
            )

            # Filter for likely DEX contracts by probing
            dex_contracts = []
            for contract in contracts:
                try:
                    # Quick check: look for common DEX methods
                    classification = client.classify_contract(
                        args.chain, contract.address
                    )
                    if classification.get("suggested_protocol_type") == "dex":
                        dex_contracts.append(
                            {
                                "address": contract.address,
                                "protocol": classification.get(
                                    "suggested_role", "unknown"
                                ),
                                "confidence": classification.get("confidence", 0),
                                "methods": len(
                                    classification.get("interaction_methods", [])
                                ),
                            }
                        )
                except:
                    pass

                if len(dex_contracts) >= args.limit:
                    break

            if args.format == "json":
                print(json.dumps(dex_contracts, indent=2))
            else:
                print(f"DEX contracts on {args.chain} ({len(dex_contracts)}):")
                print("-" * 80)
                print(
                    f"{'Address':<44} {'Role':<15} {'Confidence':<12} {'Methods':<10}"
                )
                print("-" * 80)
                for dex in dex_contracts:
                    print(
                        f"{dex['address']:<44} {dex['protocol']:<15} {dex['confidence']:<12.2f} {dex['methods']:<10}"
                    )

        elif args.command == "db":
            import sqlite3

            db_path = (
                Path.home() / ".hermes" / "data" / "defillama_verified_contracts.db"
            )

            if args.info:
                print(f"Database: {db_path}")
                print(f"Exists: {db_path.exists()}")
                if db_path.exists():
                    print(f"Size: {db_path.stat().st_size / 1024 / 1024:.2f} MB")

                    conn = sqlite3.connect(str(db_path))
                    cursor = conn.execute("SELECT COUNT(*) FROM verified_contracts")
                    count = cursor.fetchone()[0]
                    print(f"Total contracts: {count}")

                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM verified_contracts WHERE verification_status = 'deployed'"
                    )
                    deployed = cursor.fetchone()[0]
                    print(f"Deployed: {deployed}")

                    cursor = conn.execute(
                        "SELECT COUNT(DISTINCT chain) FROM verified_contracts"
                    )
                    chains = cursor.fetchone()[0]
                    print(f"Chains: {chains}")

                    conn.close()

            elif args.tables:
                if db_path.exists():
                    conn = sqlite3.connect(str(db_path))
                    cursor = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                    tables = cursor.fetchall()

                    print("Tables:")
                    for table in tables:
                        table_name = table[0]
                        print(f"\n{table_name}:")
                        cursor = conn.execute(f"PRAGMA table_info({table_name})")
                        columns = cursor.fetchall()
                        for col in columns:
                            print(f"  {col[1]:30s} {col[2]}")

                    conn.close()
                else:
                    print(f"Database not found: {db_path}")

            elif args.query:
                if db_path.exists():
                    conn = sqlite3.connect(str(db_path))
                    conn.row_factory = sqlite3.Row
                    try:
                        cursor = conn.execute(args.query)
                        rows = cursor.fetchall()

                        if rows:
                            # Print header
                            columns = rows[0].keys()
                            print(" | ".join(columns))
                            print("-" * (len(columns) * 15))

                            # Print rows
                            for row in rows[:50]:  # Limit to 50 rows
                                print(" | ".join(str(row[col]) for col in columns))

                            if len(rows) > 50:
                                print(f"\n... and {len(rows) - 50} more rows")
                        else:
                            print("No results")

                    except Exception as e:
                        print(f"Query error: {e}")

                    conn.close()
                else:
                    print(f"Database not found: {db_path}")

            else:
                print("Use --info, --tables, or --query <sql>")

    finally:
        client.close()


if __name__ == "__main__":
    main()
