#!/usr/bin/env python3
"""
defillama-cli: Comprehensive CLI for interacting with the DefiLlama ecosystem.

Provides access to:
  - DefiLlama APIs (protocols, chains, DEXs, yields, fees, bridges, stablecoins)
  - Extracted local data (factory addresses, RPCs, core assets, bridge adapters)
  - On-chain operations (quotes, pool discovery)
  - Chain/protocol/DEX search and discovery

Usage:
  python3 defillama-cli.py chains [--search NAME] [--top N]
  python3 defillama-cli.py chain <name> [--rpcs] [--dexs] [--bridges] [--assets]
  python3 defillama-cli.py protocols [--chain CHAIN] [--category CAT] [--top N]
  python3 defillama-cli.py protocol <slug>
  python3 defillama-cli.py dexs [--chain CHAIN] [--search NAME]
  python3 defillama-cli.py dex <name> [--chain CHAIN]
  python3 defillama-cli.py bridges [--chain CHAIN]
  python3 defillama-cli.py yields [--chain CHAIN] [--min-apy N] [--top N]
  python3 defillama-cli.py rpc <chain>
  python3 defillama-cli.py assets <chain>
  python3 defillama-cli.py quote <chain> <token_in> <token_out> [--amount N]
  python3 defillama-cli.py search <query>
  python3 defillama-cli.py stats
  python3 defillama-cli.py registry [name]
"""

import argparse
import json
import os
import sys
import time
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
# TOR proxy - route all external HTTP through SOCKS5
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-token-screener"))
import hermes_screener.tor_config

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Add local module path
CLI_DIR = Path(__file__).parent
sys.path.insert(0, str(CLI_DIR))
sys.path.insert(0, str(Path.home() / ".hermes/data/defillama_unified"))

try:
    import defillama_unified as dlu

    HAS_LOCAL = True
except ImportError:
    HAS_LOCAL = False

###############################################################################
# Constants
###############################################################################

DEFILLAMA_API = "https://api.llama.fi"
YIELD_API = "https://yields.llama.fi"
STABLECOIN_API = "https://stablecoins.llama.fi"
BRIDGE_API = "https://bridges.llama.fi"


# Colors for terminal output
class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    RESET = "\033[0m"


NO_COLOR = os.environ.get("NO_COLOR", "0") == "1"


def c(code, text):
    if NO_COLOR:
        return str(text)
    return f"{code}{text}{C.RESET}"


###############################################################################
# API helpers
###############################################################################


def api_get(url: str, timeout: int = 15) -> Any:
    """Make a GET request to a DefiLlama API endpoint."""
    if not HAS_REQUESTS:
        print(
            "Error: 'requests' library required. pip install requests", file=sys.stderr
        )
        sys.exit(1)
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None


def format_number(n, decimals=2):
    """Format large numbers with K/M/B suffixes."""
    if n is None:
        return "N/A"
    if abs(n) >= 1e9:
        return f"${n/1e9:.{decimals}f}B"
    if abs(n) >= 1e6:
        return f"${n/1e6:.{decimals}f}M"
    if abs(n) >= 1e3:
        return f"${n/1e3:.{decimals}f}K"
    return f"${n:.{decimals}f}"


def format_pct(n):
    if n is None:
        return "N/A"
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.2f}%"


def truncate(s, maxlen=60):
    if not s:
        return ""
    s = str(s)
    return s[: maxlen - 3] + "..." if len(s) > maxlen else s


def output_json(data):
    """Output data as formatted JSON."""
    print(json.dumps(data, indent=2, default=str))


def output_table(rows, headers, max_col_width=40):
    """Output data as an aligned table."""
    if not rows:
        print("No data.")
        return

    # Calculate column widths
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], min(len(str(val)), max_col_width))

    # Header
    header_line = "  ".join(
        c(C.BOLD, str(h).ljust(widths[i])) for i, h in enumerate(headers)
    )
    print(header_line)
    print("  ".join("-" * w for w in widths))

    # Rows
    for row in rows:
        parts = []
        for i, val in enumerate(row):
            s = str(val) if val is not None else ""
            if len(s) > max_col_width:
                s = s[: max_col_width - 3] + "..."
            parts.append(s.ljust(widths[i]))
        print("  ".join(parts))


###############################################################################
# Command: chains
###############################################################################


def cmd_chains(args):
    """List/search chains."""
    if HAS_LOCAL and not args.api:
        inst = dlu.get_instance()
        chains = inst.get_chains()

        if args.search:
            search = args.search.lower()
            chains = [c for c in chains if search in c.lower()]

        summary = inst.get_chain_summary()

        # Sort by DEX count, RPC count, or name
        if args.sort == "dex":
            chains = sorted(
                chains,
                key=lambda c: summary.get(c, {}).get("dex_factory_count", 0),
                reverse=True,
            )
        elif args.sort == "rpc":
            chains = sorted(
                chains,
                key=lambda c: summary.get(c, {}).get("rpc_count", 0),
                reverse=True,
            )
        elif args.sort == "bridge":
            chains = sorted(
                chains,
                key=lambda c: summary.get(c, {}).get("bridge_count", 0),
                reverse=True,
            )
        else:
            chains = sorted(chains)

        if args.top:
            chains = chains[: args.top]

        if args.json:
            output_json([{"name": c, **summary.get(c, {})} for c in chains])
        else:
            rows = []
            for chain in chains:
                info = summary.get(chain, {})
                rows.append(
                    [
                        chain,
                        info.get("dex_factory_count", 0),
                        info.get("lending_count", 0),
                        info.get("bridge_count", 0),
                        info.get("rpc_count", 0),
                        "Yes" if info.get("has_core_assets") else "No",
                    ]
                )
            output_table(rows, ["Chain", "DEX", "Lend", "Bridge", "RPC", "Assets"])
    else:
        # Use live API
        data = api_get(f"{DEFILLAMA_API}/v2/chains")
        if not data:
            return

        if args.search:
            search = args.search.lower()
            data = [c for c in data if search in c.get("name", "").lower()]

        if args.top:
            data = sorted(data, key=lambda c: c.get("tvl", 0), reverse=True)[: args.top]

        if args.json:
            output_json(data)
        else:
            rows = []
            for c in data:
                rows.append(
                    [
                        c.get("name", ""),
                        c.get("chainId", ""),
                        format_number(c.get("tvl", 0)),
                        c.get("tokenSymbol", ""),
                    ]
                )
            output_table(rows, ["Chain", "ID", "TVL", "Symbol"])


###############################################################################
# Command: chain
###############################################################################


def cmd_chain(args):
    """Show chain details."""
    name = args.name.lower()

    if HAS_LOCAL:
        inst = dlu.get_instance()
        info = inst.get_chain_info(name)
        rpcs = inst.get_rpcs(name)
        assets = inst.get_core_assets(name)
        factories = inst.get_dex_factories(name)
        bridges = inst.get_bridges_on_chain(name)
        lending = inst.get_lending_protocols(name)

        if args.json:
            output_json(
                {
                    "chain": name,
                    "info": info,
                    "rpcs": rpcs[: args.limit],
                    "assets": assets,
                    "dex_factories": factories[: args.limit],
                    "bridges": bridges[: args.limit],
                    "lending": lending[: args.limit],
                }
            )
        else:
            print(c(C.BOLD, f"Chain: {name}"))
            print(f"  DEX factories: {len(factories)}")
            print(f"  Lending protocols: {len(lending)}")
            print(f"  Bridges: {len(bridges)}")
            print(f"  RPCs: {len(rpcs)}")
            print(f"  Core assets: {len(assets)}")

            if args.rpcs and rpcs:
                print(c(C.CYAN, "\n  RPC Endpoints:"))
                for rpc in rpcs[: args.limit]:
                    print(f"    {rpc}")

            if args.assets and assets:
                print(c(C.CYAN, "\n  Core Assets:"))
                for sym, addr in list(assets.items())[: args.limit]:
                    print(f"    {sym}: {addr}")

            if args.dexs and factories:
                print(c(C.CYAN, "\n  DEX Factories:"))
                for f in factories[: args.limit]:
                    print(f"    {f['protocol']} v{f['version']}: {f['factory']}")

            if args.bridges and bridges:
                print(c(C.CYAN, "\n  Bridges:"))
                for b in bridges[: args.limit]:
                    print(f"    {b['protocol']}: {b.get('addresses', [])[:2]}")
    else:
        # Live API fallback
        chains = api_get(f"{DEFILLAMA_API}/v2/chains")
        if chains:
            match = next((c for c in chains if c["name"].lower() == name), None)
            if match:
                output_json(match) if args.json else print(json.dumps(match, indent=2))


###############################################################################
# Command: protocols
###############################################################################


def cmd_protocols(args):
    """List/search protocols."""
    if HAS_LOCAL and not args.api:
        inst = dlu.get_instance()

        if args.chain:
            protocols = inst.get_protocols(args.chain)
        elif args.search:
            protocols = inst.search_protocol(args.search)
        else:
            protocols = inst.get_protocols()

        if args.category:
            cat = args.category.lower()
            protocols = [
                p for p in protocols if cat in str(p.get("category", "")).lower()
            ]

        # Sort by TVL
        protocols = sorted(protocols, key=lambda p: p.get("tvl", 0) or 0, reverse=True)

        if args.top:
            protocols = protocols[: args.top]

        if args.json:
            output_json(protocols)
        else:
            rows = []
            for p in protocols[: args.limit]:
                name = p.get("name", p.get("slug", ""))
                rows.append(
                    [
                        truncate(name, 30),
                        p.get("category", ""),
                        format_number(p.get("tvl", 0)),
                        len(p.get("chains", [])),
                        p.get("slug", ""),
                    ]
                )
            output_table(rows, ["Name", "Category", "TVL", "Chains", "Slug"])
    else:
        # Live API
        data = api_get(f"{DEFILLAMA_API}/protocols")
        if not data:
            return

        if args.search:
            s = args.search.lower()
            data = [
                p
                for p in data
                if s in p.get("name", "").lower() or s in p.get("slug", "").lower()
            ]
        if args.chain:
            ch = args.chain.lower()
            data = [p for p in data if ch in [c.lower() for c in p.get("chains", [])]]
        if args.category:
            cat = args.category.lower()
            data = [p for p in data if cat in str(p.get("category", "")).lower()]

        data = sorted(data, key=lambda p: p.get("tvl", 0) or 0, reverse=True)
        if args.top:
            data = data[: args.top]

        if args.json:
            output_json(data[: args.limit])
        else:
            rows = []
            for p in data[: args.limit]:
                rows.append(
                    [
                        truncate(p.get("name", ""), 30),
                        p.get("category", ""),
                        format_number(p.get("tvl", 0)),
                        len(p.get("chains", [])),
                    ]
                )
            output_table(rows, ["Name", "Category", "TVL", "Chains"])


###############################################################################
# Command: protocol
###############################################################################


def cmd_protocol(args):
    """Show protocol details."""
    slug = args.slug

    if HAS_LOCAL:
        inst = dlu.get_instance()
        results = inst.search_protocol(slug)

        if not results:
            print(f"No protocol found matching '{slug}'", file=sys.stderr)
            return

        proto = results[0]

        if args.json:
            output_json(proto)
        else:
            print(c(C.BOLD, f"Protocol: {proto.get('name', '')}"))
            print(f"  Slug: {proto.get('slug', '')}")
            print(f"  Category: {proto.get('category', '')}")
            print(f"  TVL: {format_number(proto.get('tvl', 0))}")
            print(f"  Chains: {', '.join(proto.get('chains', [])[:15])}")
            print(f"  Address: {proto.get('address', 'N/A')}")
            print(f"  URL: {proto.get('url', 'N/A')}")
    else:
        data = api_get(f"{DEFILLAMA_API}/protocol/{slug}")
        if data:
            output_json(data) if args.json else print(json.dumps(data, indent=2))


###############################################################################
# Command: dexs
###############################################################################


def cmd_dexs(args):
    """List DEXs on a chain or search."""
    if HAS_LOCAL:
        inst = dlu.get_instance()

        if args.chain:
            chain = dlu.normalize_chain(args.chain)
            factories = inst.get_dex_factories(chain)
            # Add chain to each factory
            for f in factories:
                f["chain"] = chain
        elif args.search:
            # Search across all
            search = args.search.lower()
            factories = []
            for chain_name, chain_data in inst._chains.items():
                for f in chain_data.get("dex_factories", []):
                    if search in f.get("protocol", "").lower():
                        factories.append({"chain": chain_name, **f})
        else:
            # All DEX factories
            factories = []
            for chain_name, chain_data in inst._chains.items():
                for f in chain_data.get("dex_factories", []):
                    factories.append({"chain": chain_name, **f})

        # Deduplicate by (protocol, version)
        seen = set()
        unique = []
        for f in factories:
            key = (f.get("protocol", ""), f.get("version", ""))
            if key not in seen:
                seen.add(key)
                unique.append(f)

        if args.json:
            output_json(unique[: args.limit])
        else:
            rows = []
            for f in unique[: args.limit]:
                rows.append(
                    [
                        f.get("chain", ""),
                        f.get("protocol", ""),
                        f.get("version", ""),
                        f.get("factory", "")[:20] + "..." if f.get("factory") else "",
                    ]
                )
            output_table(rows, ["Chain", "Protocol", "Ver", "Factory"])
    else:
        # Live API
        data = api_get(f"{DEFILLAMA_API}/overview/dexs")
        if data and "protocols" in data:
            protocols = data["protocols"]
            if args.search:
                s = args.search.lower()
                protocols = [p for p in protocols if s in p.get("name", "").lower()]
            protocols = sorted(
                protocols, key=lambda p: p.get("total24h", 0) or 0, reverse=True
            )
            if args.json:
                output_json(protocols[: args.limit])
            else:
                rows = []
                for p in protocols[: args.limit]:
                    rows.append(
                        [
                            truncate(p.get("name", ""), 30),
                            format_number(p.get("total24h", 0)),
                            format_number(p.get("total7d", 0)),
                        ]
                    )
                output_table(rows, ["DEX", "24h Vol", "7d Vol"])


###############################################################################
# Command: dex
###############################################################################


def cmd_dex(args):
    """Show DEX details."""
    name = args.name.lower()

    if HAS_LOCAL:
        inst = dlu.get_instance()

        # Search in factories
        found = []
        for chain_name, chain_data in inst._chains.items():
            for f in chain_data.get("dex_factories", []):
                if name in f.get("protocol", "").lower():
                    found.append({"chain": chain_name, **f})

        # Search in registries
        registry_data = {}
        for reg_name in ["uniswapV2", "uniswapV3"]:
            reg = inst.get_registry_addresses(reg_name)
            for proto, chains in reg.items():
                if name in proto.lower():
                    registry_data[f"{reg_name}/{proto}"] = {
                        chain: addrs[:5] for chain, addrs in chains.items()
                    }

        if args.json:
            output_json({"factories": found, "registries": registry_data})
        else:
            print(c(C.BOLD, f"DEX: {args.name}"))
            print(f"  Factory entries: {len(found)}")

            if found:
                print(c(C.CYAN, "\n  Factory Addresses:"))
                for f in found[: args.limit]:
                    print(
                        f"    {f['chain']}: {f.get('factory', '')} (v{f.get('version', '?')})"
                    )

            if registry_data:
                print(c(C.CYAN, "\n  Registry Entries:"))
                for reg_key, chains in registry_data.items():
                    print(f"    {reg_key}:")
                    for chain, addrs in list(chains.items())[:5]:
                        print(f"      {chain}: {addrs[:3]}")


###############################################################################
# Command: bridges
###############################################################################


def cmd_bridges(args):
    """List bridges."""
    if HAS_LOCAL:
        inst = dlu.get_instance()

        if args.chain:
            bridges = inst.get_bridges_on_chain(args.chain)
            if args.json:
                output_json(bridges)
            else:
                for b in bridges[: args.limit]:
                    print(f"  {b['protocol']}: {b.get('addresses', [])[:3]}")
        else:
            all_bridges = inst.get_bridge_adapters()
            if args.search:
                s = args.search.lower()
                all_bridges = {k: v for k, v in all_bridges.items() if s in k.lower()}

            if args.json:
                output_json(dict(list(all_bridges.items())[: args.limit]))
            else:
                rows = []
                for name, info in list(all_bridges.items())[: args.limit]:
                    rows.append(
                        [
                            name,
                            len(info.get("addresses", [])),
                            len(info.get("chains", [])),
                            ", ".join(info.get("events", [])[:3]),
                        ]
                    )
                output_table(rows, ["Bridge", "Addrs", "Chains", "Events"])
    else:
        data = api_get(f"{BRIDGE_API}/bridges")
        if data:
            if args.json:
                output_json(data[: args.limit])
            else:
                rows = []
                for b in data[: args.limit]:
                    rows.append(
                        [
                            b.get("name", ""),
                            b.get("displayName", ""),
                            len(b.get("destinationChain", []) or []),
                        ]
                    )
                output_table(rows, ["Bridge", "Display", "Dest Chains"])


###############################################################################
# Command: yields
###############################################################################


def cmd_yields(args):
    """List yield opportunities."""
    if HAS_LOCAL and not args.api:
        inst = dlu.get_instance()
        yields = inst.get_yield_adaptors()

        if args.search:
            s = args.search.lower()
            yields = {k: v for k, v in yields.items() if s in k.lower()}

        if args.json:
            output_json(dict(list(yields.items())[: args.limit]))
        else:
            rows = []
            for name, info in list(yields.items())[: args.limit]:
                rows.append(
                    [
                        name,
                        len(info.get("addresses", [])),
                        ", ".join(info.get("chains", [])[:3]),
                    ]
                )
            output_table(rows, ["Yield Protocol", "Addrs", "Chains"])
    else:
        data = api_get(f"{YIELD_API}/pools")
        if data and "data" in data:
            pools = data["data"]
            if args.chain:
                ch = args.chain.lower()
                pools = [p for p in pools if ch in str(p.get("chain", "")).lower()]
            if args.min_apy:
                pools = [p for p in pools if (p.get("apy", 0) or 0) >= args.min_apy]
            pools = sorted(pools, key=lambda p: p.get("apy", 0) or 0, reverse=True)

            if args.json:
                output_json(pools[: args.limit])
            else:
                rows = []
                for p in pools[: args.limit]:
                    rows.append(
                        [
                            truncate(p.get("project", ""), 20),
                            truncate(p.get("symbol", ""), 20),
                            p.get("chain", ""),
                            f"{p.get('apy', 0):.2f}%",
                            format_number(p.get("tvlUsd", 0)),
                        ]
                    )
                output_table(rows, ["Project", "Symbol", "Chain", "APY", "TVL"])


###############################################################################
# Command: rpc
###############################################################################


def cmd_rpc(args):
    """Get RPC endpoints for a chain."""
    chain = args.chain.lower()

    if HAS_LOCAL:
        inst = dlu.get_instance()
        rpcs = inst.get_rpcs(chain)

        if args.json:
            output_json({"chain": chain, "rpcs": rpcs})
        else:
            print(c(C.BOLD, f"RPC Endpoints for {chain}:"))
            for i, rpc in enumerate(rpcs[: args.limit], 1):
                print(f"  {i}. {rpc}")

    if args.verify and HAS_REQUESTS:
        print(c(C.YELLOW, "\nVerifying RPCs..."))
        for rpc in rpcs[:5]:
            try:
                resp = requests.post(
                    rpc,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_blockNumber",
                        "params": [],
                    },
                    timeout=5,
                )
                if resp.status_code == 200:
                    result = resp.json().get("result", "")
                    block = int(result, 16) if result else 0
                    print(c(C.GREEN, f"  ✓ {rpc[:60]} -> block {block}"))
                else:
                    print(c(C.RED, f"  ✗ {rpc[:60]} -> HTTP {resp.status_code}"))
            except Exception as e:
                print(c(C.RED, f"  ✗ {rpc[:60]} -> {e}"))


###############################################################################
# Command: assets
###############################################################################


def cmd_assets(args):
    """Get core assets for a chain."""
    chain = args.chain.lower()

    if HAS_LOCAL:
        inst = dlu.get_instance()
        assets = inst.get_core_assets(chain)

        if args.json:
            output_json({"chain": chain, "assets": assets})
        else:
            print(c(C.BOLD, f"Core Assets for {chain}:"))
            for sym, addr in assets.items():
                print(f"  {sym}: {addr}")


###############################################################################
# Command: quote
###############################################################################


def cmd_quote(args):
    """Get a swap quote."""
    chain = args.chain.lower()
    token_in = args.token_in
    token_out = args.token_out
    amount = args.amount or "1000000000000000000"  # 1 ETH default

    if not HAS_REQUESTS:
        print("Error: 'requests' library required.", file=sys.stderr)
        return

    # Try multiple DEX aggregators
    results = []

    # KyberSwap
    try:
        resp = requests.post(
            f"https://aggregator-api.kyberswap.com/{chain}/api/v1/routes",
            json={"tokenIn": token_in, "tokenOut": token_out, "amountIn": str(amount)},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            route = data.get("data", {}).get("routeSummary", {})
            results.append(
                {
                    "provider": "KyberSwap",
                    "output": route.get("amountOut", "0"),
                    "gas": route.get("gas", "0"),
                }
            )
    except:
        pass

    # 1inch
    try:
        resp = requests.get(
            f"https://api.1inch.dev/swap/v6.0/1/quote",
            params={"src": token_in, "dst": token_out, "amount": str(amount)},
            headers={"Authorization": "Bearer " + os.environ.get("ONEINCH_KEY", "")},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            results.append(
                {
                    "provider": "1inch",
                    "output": data.get("dstAmount", "0"),
                    "gas": data.get("gas", "0"),
                }
            )
    except:
        pass

    if args.json:
        output_json(
            {
                "chain": chain,
                "token_in": token_in,
                "token_out": token_out,
                "quotes": results,
            }
        )
    else:
        print(
            c(
                C.BOLD,
                f"Quotes for {token_in[:10]}... -> {token_out[:10]}... on {chain}",
            )
        )
        for q in results:
            print(f"  {q['provider']}: output={q['output']}, gas={q['gas']}")


###############################################################################
# Command: search
###############################################################################


def cmd_search(args):
    """Search across all data."""
    query = args.query.lower()

    results = {
        "chains": [],
        "protocols": [],
        "dexs": [],
        "bridges": [],
    }

    if HAS_LOCAL:
        inst = dlu.get_instance()

        # Chains
        for chain in inst.get_chains():
            if query in chain.lower():
                results["chains"].append(chain)

        # Protocols
        results["protocols"] = inst.search_protocol(query)

        # DEXs
        for chain_name, chain_data in inst._chains.items():
            for f in chain_data.get("dex_factories", []):
                if query in f.get("protocol", "").lower():
                    results["dexs"].append({"chain": chain_name, **f})

        # Bridges
        for name, info in inst.get_bridge_adapters().items():
            if query in name.lower():
                results["bridges"].append({"name": name, **info})

    if args.json:
        output_json(results)
    else:
        print(c(C.BOLD, f"Search results for '{args.query}':"))

        if results["chains"]:
            print(c(C.CYAN, f"\n  Chains ({len(results['chains'])}):"))
            for ch in results["chains"][:5]:
                print(f"    {ch}")

        if results["protocols"]:
            print(c(C.CYAN, f"\n  Protocols ({len(results['protocols'])}):"))
            for p in results["protocols"][:5]:
                print(f"    {p.get('name', '')}: TVL={format_number(p.get('tvl', 0))}")

        if results["dexs"]:
            print(c(C.CYAN, f"\n  DEXs ({len(results['dexs'])}):"))
            for d in results["dexs"][:5]:
                print(
                    f"    {d.get('protocol', '')} on {d.get('chain', '')}: {d.get('factory', '')[:30]}"
                )

        if results["bridges"]:
            print(c(C.CYAN, f"\n  Bridges ({len(results['bridges'])}):"))
            for b in results["bridges"][:5]:
                print(
                    f"    {b.get('name', '')}: {len(b.get('addresses', []))} addresses"
                )


###############################################################################
# Command: stats
###############################################################################


def cmd_stats(args):
    """Show aggregate statistics."""
    if HAS_LOCAL:
        inst = dlu.get_instance()
        inst._load_all()

        stats = {
            "chains": len(inst._chains),
            "protocols": len(inst._protocols),
            "dex_factory_protocols": len(inst._dex_factories),
            "bridge_adapters": len(inst._bridge_adapters),
            "yield_adaptors": len(inst._yield_adaptors),
            "rpc_chains": len(inst._rpc_endpoints),
            "core_asset_chains": len(inst._core_assets),
            "registries": list(inst._registry_addresses.keys()),
            "registry_protocols": {
                k: len(v) for k, v in inst._registry_addresses.items()
            },
            "top_chains_by_dex": inst.get_top_chains("dex", 10),
            "top_chains_by_rpc": inst.get_top_chains("rpc", 10),
        }

        if args.json:
            output_json(stats)
        else:
            print(c(C.BOLD, "DefiLlama Unified Statistics"))
            print(f"  Chains: {stats['chains']:,}")
            print(f"  Protocols: {stats['protocols']:,}")
            print(f"  DEX factory protocols: {stats['dex_factory_protocols']:,}")
            print(f"  Bridge adapters: {stats['bridge_adapters']:,}")
            print(f"  Yield adaptors: {stats['yield_adaptors']:,}")
            print(f"  Chains with RPCs: {stats['rpc_chains']:,}")
            print(f"  Chains with core assets: {stats['core_asset_chains']:,}")

            print(c(C.CYAN, "\n  Top chains by DEX factories:"))
            for chain, count in stats["top_chains_by_dex"]:
                print(f"    {chain}: {count}")
    else:
        # Live API stats
        chains = api_get(f"{DEFILLAMA_API}/v2/chains")
        protocols = api_get(f"{DEFILLAMA_API}/protocols")
        dexs = api_get(f"{DEFILLAMA_API}/overview/dexs")

        if args.json:
            output_json(
                {
                    "api_chains": len(chains) if chains else 0,
                    "api_protocols": len(protocols) if protocols else 0,
                    "api_dexs": len(dexs.get("protocols", [])) if dexs else 0,
                }
            )
        else:
            print(c(C.BOLD, "DefiLlama API Live Statistics"))
            print(f"  Chains: {len(chains) if chains else 'N/A'}")
            print(f"  Protocols: {len(protocols) if protocols else 'N/A'}")
            print(f"  DEXs: {len(dexs.get('protocols', [])) if dexs else 'N/A'}")


###############################################################################
# Command: registry
###############################################################################


def cmd_registry(args):
    """Show DefiLlama-Adapters registry data."""
    if not HAS_LOCAL:
        print("Error: Local data required for registry command.", file=sys.stderr)
        return

    inst = dlu.get_instance()
    reg = inst.get_registry_addresses(args.name)

    if args.json:
        output_json(reg)
    else:
        if args.name:
            print(c(C.BOLD, f"Registry: {args.name}"))
            for proto, chains in reg.items():
                total = sum(len(addrs) for addrs in chains.values())
                print(f"  {proto}: {len(chains)} chains, {total} addresses")
                if args.verbose:
                    for chain, addrs in list(chains.items())[:5]:
                        print(f"    {chain}: {addrs[:3]}")
        else:
            print(c(C.BOLD, "Available Registries:"))
            for name, data in inst._registry_addresses.items():
                total_protos = len(data)
                total_addrs = sum(
                    len(addrs) for proto in data.values() for addrs in proto.values()
                )
                print(f"  {name}: {total_protos} protocols, {total_addrs} addresses")


###############################################################################
# Main CLI
###############################################################################


def main():
    parser = argparse.ArgumentParser(
        prog="defillama-cli",
        description="Comprehensive CLI for interacting with the DefiLlama ecosystem",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s chains --top 20 --sort dex
  %(prog)s chain base --rpcs --dexs --assets
  %(prog)s protocols --chain ethereum --top 10
  %(prog)s dexs --chain base --search aero
  %(prog)s rpc ethereum --verify
  %(prog)s search uniswap
  %(prog)s yields --chain base --min-apy 5 --top 10
  %(prog)s quote base 0x...WETH 0x...USDC --amount 1000000000000000000
  %(prog)s registry uniswapV2 --verbose
  %(prog)s stats
""",
    )

    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--api", action="store_true", help="Force live API (skip local data)"
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=50, help="Max results to show"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # chains
    p = subparsers.add_parser("chains", help="List/search chains")
    p.add_argument("--search", "-s", help="Search chain name")
    p.add_argument("--top", "-t", type=int, help="Top N chains")
    p.add_argument("--sort", choices=["name", "dex", "rpc", "bridge"], default="name")
    p.set_defaults(func=cmd_chains)

    # chain
    p = subparsers.add_parser("chain", help="Chain details")
    p.add_argument("name", help="Chain name")
    p.add_argument("--rpcs", action="store_true", help="Show RPCs")
    p.add_argument("--dexs", action="store_true", help="Show DEX factories")
    p.add_argument("--bridges", action="store_true", help="Show bridges")
    p.add_argument("--assets", action="store_true", help="Show core assets")
    p.set_defaults(func=cmd_chain)

    # protocols
    p = subparsers.add_parser("protocols", help="List/search protocols")
    p.add_argument("--chain", "-c", help="Filter by chain")
    p.add_argument("--category", help="Filter by category")
    p.add_argument("--search", "-s", help="Search by name")
    p.add_argument("--top", "-t", type=int, help="Top N by TVL")
    p.set_defaults(func=cmd_protocols)

    # protocol
    p = subparsers.add_parser("protocol", help="Protocol details")
    p.add_argument("slug", help="Protocol slug/name")
    p.set_defaults(func=cmd_protocol)

    # dexs
    p = subparsers.add_parser("dexs", help="List DEXs")
    p.add_argument("--chain", "-c", help="Filter by chain")
    p.add_argument("--search", "-s", help="Search by name")
    p.set_defaults(func=cmd_dexs)

    # dex
    p = subparsers.add_parser("dex", help="DEX details")
    p.add_argument("name", help="DEX name")
    p.set_defaults(func=cmd_dex)

    # bridges
    p = subparsers.add_parser("bridges", help="List bridges")
    p.add_argument("--chain", "-c", help="Filter by chain")
    p.add_argument("--search", "-s", help="Search by name")
    p.set_defaults(func=cmd_bridges)

    # yields
    p = subparsers.add_parser("yields", help="List yield opportunities")
    p.add_argument("--chain", "-c", help="Filter by chain")
    p.add_argument("--search", "-s", help="Search by name")
    p.add_argument("--min-apy", type=float, help="Minimum APY")
    p.add_argument("--top", "-t", type=int, help="Top N by APY")
    p.set_defaults(func=cmd_yields)

    # rpc
    p = subparsers.add_parser("rpc", help="Get RPC endpoints")
    p.add_argument("chain", help="Chain name")
    p.add_argument("--verify", "-v", action="store_true", help="Verify RPCs work")
    p.set_defaults(func=cmd_rpc)

    # assets
    p = subparsers.add_parser("assets", help="Get core assets")
    p.add_argument("chain", help="Chain name")
    p.set_defaults(func=cmd_assets)

    # quote
    p = subparsers.add_parser("quote", help="Get swap quote")
    p.add_argument("chain", help="Chain name")
    p.add_argument("token_in", help="Input token address")
    p.add_argument("token_out", help="Output token address")
    p.add_argument("--amount", "-a", help="Amount in wei")
    p.set_defaults(func=cmd_quote)

    # search
    p = subparsers.add_parser("search", help="Search everything")
    p.add_argument("query", help="Search query")
    p.set_defaults(func=cmd_search)

    # stats
    p = subparsers.add_parser("stats", help="Aggregate statistics")
    p.set_defaults(func=cmd_stats)

    # registry
    p = subparsers.add_parser("registry", help="Show registry data")
    p.add_argument(
        "name",
        nargs="?",
        help="Registry name (uniswapV2, uniswapV3, compound, aave, etc.)",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Show details")
    p.set_defaults(func=cmd_registry)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
