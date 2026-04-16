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


MCAP_TIERS = [
    (0, 50_000, "< $50K"),
    (50_000, 250_000, "$50K - $250K"),
    (250_000, 1_000_000, "$250K - $1M"),
    (1_000_000, 10_000_000, "$1M - $10M"),
    (10_000_000, 100_000_000, "$10M - $100M"),
    (100_000_000, float("inf"), "$100M+"),
]


def mcap_tier_label(fdv: float) -> str:
    """Return market cap tier label for a given FDV."""
    for low, high, label in MCAP_TIERS:
        if low <= (fdv or 0) < high:
            return label
    return "< $50K"


def mcap_tier_key(fdv: float) -> int:
    """Return sort key for market cap tier."""
    for i, (low, high, _) in enumerate(MCAP_TIERS):
        if low <= (fdv or 0) < high:
            return i
    return 0


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
                fdv = t.get("fdv") or t.get("market_cap") or 0
                t["mcap_tier"] = mcap_tier_label(fdv)
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
    # Build token FDV lookup for wallet tier classification
    token_fdv = {}
    for t in tokens:
        addr = t.get("contract_address", "")
        if addr:
            fdv = t.get("fdv") or t.get("market_cap") or 0
            token_chain = normalize_chain(t.get("chain", ""), t.get("dex_url", ""))
            token_fdv[addr] = {"fdv": fdv, "chain": token_chain}

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

            # Get symbols and FDVs of held tokens
            held_symbols = []
            held_fdvs = []
            held_chains = set()
            for t in tokens:
                if t.get("contract_address") in overlap:
                    held_symbols.append(t.get("symbol", "?"))
                    fdv = t.get("fdv") or t.get("market_cap") or 0
                    held_fdvs.append(fdv)
                    t_chain = normalize_chain(t.get("chain", ""), t.get("dex_url", ""))
                    if t_chain != "unknown":
                        held_chains.add(t_chain)

            # Average FDV -> market cap tier
            avg_fdv = sum(held_fdvs) / len(held_fdvs) if held_fdvs else 0

            # Include ALL wallet fields
            result = dict(w)
            result["top_token_count"] = len(overlap)
            result["top_tokens"] = held_symbols[:10]
            result["avg_fdv"] = round(avg_fdv)
            result["mcap_tier"] = mcap_tier_label(avg_fdv)
            # Use token chain if wallet chain is unknown
            if not result.get("chain") and held_chains:
                result["chain"] = sorted(held_chains)[0]
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


def export_tiered_wallets():
    """Export tokens and wallets grouped by market cap tiers for GitHub Pages."""
    from datetime import datetime, timezone

    MARKET_CAP_TIERS = [
        (0, 50_000, "micro", "$0 - $50K"),
        (50_000, 100_000, "tiny", "$50K - $100K"),
        (100_000, 250_000, "small_low", "$100K - $250K"),
        (250_000, 500_000, "small_mid", "$250K - $500K"),
        (500_000, 750_000, "small_high", "$500K - $750K"),
        (750_000, 1_000_000, "mid_low", "$750K - $1M"),
        (1_000_000, 5_000_000, "mid", "$1M - $5M"),
        (5_000_000, 10_000_000, "mid_high", "$5M - $10M"),
        (10_000_000, 50_000_000, "large_low", "$10M - $50M"),
        (50_000_000, 100_000_000, "large_high", "$50M - $100M"),
        (100_000_000, float("inf"), "mega", "$100M+"),
    ]
    tier_order = [name for _, _, name, _ in MARKET_CAP_TIERS]

    def get_market_cap(token):
        return float(token.get("fdv") or token.get("market_cap") or 0)

    def get_tier(mcap):
        for low, high, name, label in MARKET_CAP_TIERS:
            if low <= mcap < high:
                return name, label
        return "mega", "$100M+"

    # Load tokens from enriched data source (same pattern as cross exports)
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
                print(f"Tiered: using {src.name}")
                break

    if not tokens:
        print("No token data, skipping tiered wallets")
        return

    # Classify tokens by tier
    tiered_tokens = {name: [] for name in tier_order}
    tier_labels = {name: label for _, _, name, label in MARKET_CAP_TIERS}

    for t in tokens:
        mcap = get_market_cap(t)
        tier_name, _ = get_tier(mcap)
        tiered_tokens[tier_name].append(t)

    # Sort tokens within each tier by score desc
    for name in tier_order:
        tiered_tokens[name].sort(key=lambda t: t.get("score", 0) or 0, reverse=True)

    # Build wallet mapping per tier
    db_path = settings.wallets_db_path
    tiered_data = {}
    tier_order_out = []

    for tier_name in tier_order:
        tier_token_list = tiered_tokens[tier_name]
        if not tier_token_list:
            continue

        tier_token_addrs = {
            t.get("contract_address", "")
            for t in tier_token_list
            if t.get("contract_address")
        }
        tier_wallets = []

        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            try:
                placeholders = ",".join("?" * len(tier_token_addrs))
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT w.address, w.chain, w.wallet_score,
                           w.total_profit, w.win_rate, w.avg_roi, w.total_trades,
                           w.wallet_tags, w.source_tokens
                    FROM tracked_wallets w
                    JOIN wallet_token_entries e ON w.address = e.wallet_address
                    WHERE e.token_address IN ({placeholders})
                      AND w.wallet_score > 0
                    ORDER BY w.wallet_score DESC
                    LIMIT 100
                """,
                    list(tier_token_addrs),
                ).fetchall()

                for w in rows:
                    held_rows = conn.execute(
                        "SELECT token_address FROM wallet_token_entries "
                        "WHERE wallet_address = ? AND token_address IN ("
                        + placeholders
                        + ")",
                        [w["address"]] + list(tier_token_addrs),
                    ).fetchall()
                    held_in_tier = [r[0] for r in held_rows]

                    tier_wallets.append(
                        {
                            "address": w["address"],
                            "chain": w["chain"],
                            "wallet_score": w["wallet_score"],
                            "total_profit": w["total_profit"],
                            "win_rate": w["win_rate"],
                            "avg_roi": w["avg_roi"],
                            "trade_count": w["total_trades"],
                            "wallet_tags": w["wallet_tags"],
                            "tokens_held": len(held_in_tier),
                            "token_addresses": held_in_tier[:5],
                        }
                    )
            except Exception as e:
                print(f"ERROR reading tier {tier_name} wallets: {e}")
            finally:
                conn.close()

        # Convert sets to lists in tokens
        clean_tokens = []
        for t in tier_token_list:
            ct = dict(t)
            for key in list(ct.keys()):
                if isinstance(ct[key], set):
                    ct[key] = list(ct[key])
            clean_tokens.append(ct)

        tiered_data[tier_name] = {
            "label": tier_labels[tier_name],
            "token_count": len(clean_tokens),
            "wallet_count": len(tier_wallets),
            "tokens": clean_tokens,
            "wallets": tier_wallets,
        }
        tier_order_out.append(tier_name)

    output = {
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "tier_order": tier_order_out,
        "tiers": tiered_data,
    }

    dst = DOCS_DATA / "tiered-wallets.json"
    with open(dst, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Exported tiered wallets ({len(tier_order_out)} tiers) to {dst}")


if __name__ == "__main__":
    print("Exporting data for GitHub Pages...")
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    export_tokens()
    export_wallets()
    export_cross_tokens()
    export_cross_wallets()
    export_tiered_wallets()
    print("\nDone! Now commit and push the docs/data/ folder:")
    print("  cd /path/to/hermes-token-screener")
    print("  git add docs/data/")
    print("  git commit -m 'update site data'")
    print("  git push")
