#!/usr/bin/env python3
"""
Export data for GitHub Pages static site.

Run this on your server to generate JSON files for the GitHub Pages dashboard.
Then commit and push the docs/data/ folder to update the live site.

Usage:
    python3 scripts/export_github_pages.py
    cd docs && git add data/ && git commit -m "update data" && git push
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from hermes_screener.config import settings

# Chain name mapping from Dexscreener URL paths
CHAIN_MAP = {
    "solana": "solana",
    "sol": "solana",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "base": "base",
    "bsc": "BNB",
    "binance": "BNB",
    "arbitrum": "Arbitrum",
    "polygon": "Polygon",
    "avalanche": "Avalanche",
    "sui": "Sui",
}


def normalize_chain(chain: str, dex_url: str = "") -> str:
    """Normalize chain name, deriving from dex_url if needed."""
    # Try to extract chain from dex_url (https://dexscreener.com/{chain}/{addr})
    if dex_url:
        parts = dex_url.split("/")
        if len(parts) >= 4 and "dexscreener.com" in dex_url:
            url_chain = parts[3].lower()
            if url_chain in CHAIN_MAP:
                return CHAIN_MAP[url_chain]

    # Fall back to chain field
    chain_lower = (chain or "").lower()
    return CHAIN_MAP.get(chain_lower, chain or "unknown")


DOCS_DATA = Path(__file__).parent.parent / "docs" / "data"


def export_tokens():
    """Export top100.json for GitHub Pages."""
    # Prefer the enriched phase files over the raw top100.json
    data_dir = settings.output_path.parent
    candidates = [
        data_dir / "top100_phase4_social.json",
        data_dir / "top100_phase3_smartmoney.json",
        data_dir / "top100_phase1_initial.json",
        settings.output_path,
    ]

    data = None
    for src in candidates:
        if src.exists():
            with open(src) as f:
                raw = json.load(f)
            # Check if it has the enriched format (contract_address field)
            tokens = raw.get("tokens") or raw.get("top_tokens") or []
            if tokens and tokens[0].get("contract_address"):
                data = raw
                print(f"Using enriched data from {src.name}")
                break

    if not data:
        print("No enriched token data found, creating empty data")
        data = {
            "tokens": [],
            "generated_at_iso": "No data available",
            "total_candidates": 0,
        }

    # Handle both "tokens" and "top_tokens" key names
    tokens = data.get("tokens") or data.get("top_tokens") or []
    data["tokens"] = tokens

    # Normalize chains and clean up data
    for token in tokens:
        token["chain"] = normalize_chain(
            token.get("chain", ""), token.get("dex_url", "")
        )
        for key in list(token.keys()):
            if isinstance(token[key], set):
                token[key] = list(token[key])

    dst = DOCS_DATA / "tokens.json"
    with open(dst, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"Exported {len(data.get('tokens', []))} tokens to {dst}")


def export_wallets():
    """Export top wallets for GitHub Pages."""
    db_path = settings.wallets_db_path
    if not db_path.exists():
        print(f"WARNING: {db_path} not found, creating empty data")
        data = {"wallets": [], "generated_at_iso": "No data available"}
    else:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM tracked_wallets WHERE wallet_score > 0 "
                "ORDER BY wallet_score DESC LIMIT 200"
            ).fetchall()
            wallets = [dict(r) for r in rows]
            # Sort by composite: prioritize high ROI, high win rate, more trades
            wallets.sort(
                key=lambda w: (
                    (max(0.1, w.get("win_rate", 0) or 0))
                    * (1 + min(w.get("avg_roi", 0) or 0, 10))
                    * min(w.get("total_trades", 0), 100)
                ),
                reverse=True,
            )
        except Exception as e:
            print(f"ERROR reading wallets: {e}")
            wallets = []
        finally:
            conn.close()

        from datetime import datetime, timezone

        data = {
            "wallets": wallets,
            "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        }

    dst = DOCS_DATA / "wallets.json"
    with open(dst, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"Exported {len(data.get('wallets', []))} wallets to {dst}")


def export_cross_tokens():
    """Export tokens ranked by wallet count for GitHub Pages."""
    # Load tokens from enriched data source
    data_dir = settings.output_path.parent
    candidates = [
        data_dir / "top100_phase4_social.json",
        data_dir / "top100_phase3_smartmoney.json",
        data_dir / "top100_phase1_initial.json",
        settings.output_path,
    ]

    tokens = []
    for src in candidates:
        if src.exists():
            with open(src) as f:
                raw = json.load(f)
            candidate_tokens = raw.get("tokens") or raw.get("top_tokens") or []
            if candidate_tokens and candidate_tokens[0].get("contract_address"):
                tokens = candidate_tokens
                print(f"Cross-tokens: using {src.name}")
                break

    if not tokens:
        print("No enriched token data, skipping cross-tokens")
        return

    # Get wallet holdings
    db_path = settings.wallets_db_path
    if not db_path.exists():
        print("No wallet DB, exporting tokens without cross-reference")
        for t in tokens:
            t["wallet_count"] = 0
            t["holding_wallets"] = []
    else:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            # Get top wallets
            top_wallets = conn.execute(
                "SELECT address FROM tracked_wallets WHERE wallet_score > 0 "
                "ORDER BY wallet_score DESC LIMIT 200"
            ).fetchall()
            wallet_addrs = [r[0] for r in top_wallets]

            # Get holdings for each wallet
            wallet_holdings = {}  # token_addr -> set of wallet_addrs
            for w_addr in wallet_addrs:
                rows = conn.execute(
                    "SELECT DISTINCT token_address FROM wallet_token_entries "
                    "WHERE wallet_address = ? AND token_address IS NOT NULL",
                    (w_addr,),
                ).fetchall()
                for r in rows:
                    t_addr = r[0]
                    if t_addr:
                        if t_addr not in wallet_holdings:
                            wallet_holdings[t_addr] = []
                        wallet_holdings[t_addr].append(w_addr)

            # Annotate tokens
            for t in tokens:
                t_addr = t.get("contract_address", "")
                t["wallet_count"] = len(wallet_holdings.get(t_addr, []))
                t["holding_wallets"] = wallet_holdings.get(t_addr, [])[:10]
                t["chain"] = normalize_chain(t.get("chain", ""), t.get("dex_url", ""))
        finally:
            conn.close()

    # Sort by wallet_count, then score
    tokens.sort(
        key=lambda t: (t.get("wallet_count", 0), t.get("score", 0)), reverse=True
    )

    # Convert sets to lists
    for t in tokens:
        for key in list(t.keys()):
            if isinstance(t[key], set):
                t[key] = list(t[key])

    dst = DOCS_DATA / "cross-tokens.json"
    with open(dst, "w") as f:
        json.dump(tokens, f, indent=2, default=str)
    print(f"Exported {len(tokens)} cross-referenced tokens to {dst}")


def export_cross_wallets():
    """Export wallets ranked by top token count for GitHub Pages."""
    # Load tokens from enriched data source
    data_dir = settings.output_path.parent
    candidates = [
        data_dir / "top100_phase4_social.json",
        data_dir / "top100_phase3_smartmoney.json",
        data_dir / "top100_phase1_initial.json",
        settings.output_path,
    ]

    tokens = []
    for src in candidates:
        if src.exists():
            with open(src) as f:
                raw = json.load(f)
            candidate_tokens = raw.get("tokens") or raw.get("top_tokens") or []
            if candidate_tokens and candidate_tokens[0].get("contract_address"):
                tokens = candidate_tokens
                print(f"Cross-wallets: using {src.name}")
                break

    if not tokens:
        print("No enriched token data, skipping cross-wallets")
        return

    top_token_addrs = {
        t.get("contract_address", "") for t in tokens if t.get("contract_address")
    }

    # Get wallets
    db_path = settings.wallets_db_path
    if not db_path.exists():
        print("No wallet DB, skipping cross-wallets")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        top_wallets = conn.execute(
            "SELECT * FROM tracked_wallets "
            "WHERE wallet_score > 0 AND total_trades > 1 "
            "ORDER BY wallet_score DESC LIMIT 500"
        ).fetchall()

        wallet_results = []
        for w in top_wallets:
            w_addr = w["address"]
            rows = conn.execute(
                "SELECT DISTINCT token_address FROM wallet_token_entries "
                "WHERE wallet_address = ? AND token_address IS NOT NULL",
                (w_addr,),
            ).fetchall()
            held_set = {r[0] for r in rows if r[0]}
            overlap = held_set & top_token_addrs

            # Get symbols
            held_symbols = []
            for t in tokens:
                if t.get("contract_address") in overlap:
                    held_symbols.append(t.get("symbol", "?"))

            # Include ALL wallet fields
            result = dict(w)
            result["top_token_count"] = len(overlap)
            result["top_tokens"] = held_symbols[:10]
            wallet_results.append(result)
    finally:
        conn.close()

    # Sort by composite score weighted heavily by top_token_count
    # Wallets holding more top tokens = higher priority
    def wallet_sort_key(w):
        tc = w.get("top_token_count", 0)
        wr = max(0.1, w.get("win_rate", 0) or 0)
        roi = w.get("avg_roi", 0) or 0
        trades = w.get("total_trades", 0)
        # Heavy weight on token count: tc^2 rewards holding many top tokens
        # Then multiply by quality signals (win rate, ROI)
        composite = (tc**1.5) * wr * (1 + min(roi, 5)) * min(trades / 10, 10)
        return (round(composite, 2), tc, w.get("wallet_score", 0))

    wallet_results.sort(key=wallet_sort_key, reverse=True)

    dst = DOCS_DATA / "cross-wallets.json"
    with open(dst, "w") as f:
        json.dump(wallet_results, f, indent=2, default=str)
    print(f"Exported {len(wallet_results)} cross-referenced wallets to {dst}")


if __name__ == "__main__":
    print("Exporting data for GitHub Pages...")
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    export_tokens()
    export_wallets()
    export_cross_tokens()
    export_cross_wallets()
    print("\nDone! Now commit and push the docs/data/ folder:")
    print("  cd /path/to/hermes-token-screener")
    print("  git add docs/data/")
    print("  git commit -m 'update site data'")
    print("  git push")
