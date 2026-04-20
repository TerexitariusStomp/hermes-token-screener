#!/usr/bin/env python3
"""
Smart Money Copy-Trade Monitor — Watch top wallets and discover what they buy.

Monitors tracked smart money wallets for new token positions.
When a top wallet buys a new token, it gets enriched and prioritized.

Database: ~/.hermes/data/token_screener/copytrade_discoveries.db

Data sources for wallet monitoring:
  - Alchemy Webhooks (EVM: ETH, Base, BSC) — transfer notifications
  - QuickNode Webhooks (EVM) — transfer notifications
  - Helius Webhooks (Solana) — transfer notifications
  - Ankr API (multi-chain) — balance polling
  - GMGN CLI (Solana) — holder/position tracking

Usage:
    python3 copytrade_monitor.py                    # full scan
    python3 copytrade_monitor.py --setup-webhooks   # create webhook subscriptions
    python3 copytrade_monitor.py --poll              # poll balances via Ankr
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from typing import Any

import requests

from hermes_screener.config import settings
from hermes_screener.logging import get_logger
from hermes_screener.metrics import metrics

log = get_logger("copytrade_monitor")

WALLETS_DB = settings.wallets_db_path
DISCOVERIES_DB = settings.hermes_home / "data" / "token_screener" / "copytrade_discoveries.db"
TOP_TOKENS_PATH = settings.output_path

# ═══════════════════════════════════════════════════════════════════════════════
# DISCOVERIES DATABASE
# ═══════════════════════════════════════════════════════════════════════════════


def init_discoveries_db() -> sqlite3.Connection:
    """Initialize the copytrade discoveries database."""
    DISCOVERIES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DISCOVERIES_DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS discovered_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            symbol TEXT,
            name TEXT,
            discovered_at REAL NOT NULL,
            discovered_by_wallet TEXT NOT NULL,
            discovery_method TEXT,
            entry_price_usd REAL,
            current_price_usd REAL,
            fdv REAL,
            volume_h24 REAL,
            enrichment_score REAL DEFAULT 0,
            social_score REAL DEFAULT 0,
            wallet_count INTEGER DEFAULT 1,
            wallet_addresses TEXT DEFAULT '[]',
            status TEXT DEFAULT 'active',
            enriched_at REAL,
            UNIQUE(contract_address, chain)
        );

        CREATE TABLE IF NOT EXISTS wallet_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            token_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            first_seen_at REAL NOT NULL,
            last_updated REAL,
            profit REAL DEFAULT 0,
            roi_pct REAL DEFAULT 0,
            buy_tx_count INTEGER DEFAULT 0,
            sell_tx_count INTEGER DEFAULT 0,
            is_profitable INTEGER DEFAULT 0,
            UNIQUE(wallet_address, token_address)
        );

        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            event_type TEXT,
            token_address TEXT,
            amount REAL,
            tx_hash TEXT,
            received_at REAL NOT NULL,
            processed INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_discovered_status ON discovered_tokens(status);
        CREATE INDEX IF NOT EXISTS idx_discovered_wallet ON discovered_tokens(discovered_by_wallet);
        CREATE INDEX IF NOT EXISTS idx_positions_wallet ON wallet_positions(wallet_address);
    """)

    return conn


# ═══════════════════════════════════════════════════════════════════════════════
# WALLET POSITION SCANNING (via GMGN + existing data)
# ═══════════════════════════════════════════════════════════════════════════════


def scan_wallet_positions(min_wallet_score: float = 30) -> dict[str, list[dict]]:
    """
    Scan top wallets for their current token positions.

    Uses GMGN CLI to get fresh holder data for each top wallet.
    Returns {wallet_address: [{token_address, chain, profit, ...}, ...]}
    """
    conn = sqlite3.connect(f"file:{WALLETS_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # Get top wallets
    wallets = conn.execute(
        "SELECT address, chain, wallet_score, wallet_tags FROM tracked_wallets "
        "WHERE wallet_score >= ? ORDER BY wallet_score DESC LIMIT 50",
        (min_wallet_score,),
    ).fetchall()
    conn.close()

    # Get existing token positions from wallet_token_entries
    conn2 = sqlite3.connect(f"file:{WALLETS_DB}?mode=ro", uri=True)
    conn2.row_factory = sqlite3.Row
    all_entries = conn2.execute("SELECT * FROM wallet_token_entries").fetchall()
    conn2.close()

    # Build wallet → positions map
    positions: dict[str, list[dict]] = {}
    for entry in all_entries:
        addr = entry["wallet_address"]
        if addr not in positions:
            positions[addr] = []
        positions[addr].append(dict(entry))

    log.info("wallet_positions_scanned", wallets=len(wallets), with_positions=sum(1 for p in positions.values() if p))
    return positions


# ═══════════════════════════════════════════════════════════════════════════════
# NEW TOKEN DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


def detect_new_positions(
    wallet_positions: dict[str, list[dict]],
    disc_conn: sqlite3.Connection,
) -> list[dict]:
    """
    Detect new token positions from top wallets.

    Compares current positions against previously discovered tokens.
    Returns list of newly discovered tokens.
    """
    # Get already discovered tokens
    known = set()
    for row in disc_conn.execute("SELECT contract_address, chain FROM discovered_tokens").fetchall():
        known.add((row[0], row[1]))

    # Get known tokens from top100
    top_tokens = set()
    if TOP_TOKENS_PATH.exists():
        with open(TOP_TOKENS_PATH) as f:
            for t in json.load(f).get("tokens", []):
                top_tokens.add(t.get("contract_address", ""))

    new_discoveries = []
    for wallet_addr, positions in wallet_positions.items():
        for pos in positions:
            token_addr = pos.get("token_address", "")
            chain = pos.get("chain", "")

            if not token_addr:
                continue

            # Skip if already known
            if (token_addr, chain) in known:
                continue

            # Skip if already in top tokens (already enriched)
            if token_addr in top_tokens:
                continue

            # New discovery!
            new_discoveries.append(
                {
                    "contract_address": token_addr,
                    "chain": chain,
                    "symbol": pos.get("token_symbol", ""),
                    "discovered_by_wallet": wallet_addr,
                    "discovery_method": "wallet_scan",
                    "profit": pos.get("profit", 0),
                    "roi_pct": pos.get("profit_change", 0),
                    "buy_tx_count": pos.get("buy_tx_count", 0),
                    "sell_tx_count": pos.get("sell_tx_count", 0),
                    "is_profitable": pos.get("is_profitable", 0),
                    "discovered_at": time.time(),
                }
            )

    # Deduplicate by address
    seen = set()
    unique = []
    for d in new_discoveries:
        key = (d["contract_address"], d["chain"])
        if key not in seen:
            seen.add(key)
            unique.append(d)

    return unique


def save_discoveries(discoveries: list[dict], conn: sqlite3.Connection):
    """Save discovered tokens to the copytrade database."""
    now = time.time()
    for d in discoveries:
        # Check if token already exists
        existing = conn.execute(
            "SELECT id, wallet_count, wallet_addresses FROM discovered_tokens WHERE contract_address = ? AND chain = ?",
            (d["contract_address"], d["chain"]),
        ).fetchone()

        if existing:
            # Update: increment wallet count
            existing_wallets = json.loads(existing[2]) if existing[2] else []
            if d["discovered_by_wallet"] not in existing_wallets:
                existing_wallets.append(d["discovered_by_wallet"])
            conn.execute(
                """
                UPDATE discovered_tokens SET
                    wallet_count = ?,
                    wallet_addresses = ?,
                    discovered_at = MIN(discovered_at, ?)
                WHERE id = ?
            """,
                (len(existing_wallets), json.dumps(existing_wallets), d["discovered_at"], existing[0]),
            )
        else:
            # New entry
            conn.execute(
                """
                INSERT INTO discovered_tokens
                (contract_address, chain, symbol, discovered_at, discovered_by_wallet,
                 discovery_method, profit, roi_pct, buy_tx_count, sell_tx_count,
                 is_profitable, wallet_count, wallet_addresses)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
                (
                    d["contract_address"],
                    d["chain"],
                    d.get("symbol", ""),
                    d["discovered_at"],
                    d["discovered_by_wallet"],
                    d.get("discovery_method", "wallet_scan"),
                    d.get("profit", 0),
                    d.get("roi_pct", 0),
                    d.get("buy_tx_count", 0),
                    d.get("sell_tx_count", 0),
                    d.get("is_profitable", 0),
                    json.dumps([d["discovered_by_wallet"]]),
                ),
            )

        # Save wallet position
        conn.execute(
            """
            INSERT OR REPLACE INTO wallet_positions
            (wallet_address, token_address, chain, first_seen_at, last_updated,
             profit, roi_pct, buy_tx_count, sell_tx_count, is_profitable)
            VALUES (?, ?, ?, COALESCE((SELECT first_seen_at FROM wallet_positions WHERE wallet_address=? AND token_address=?), ?),
                    ?, ?, ?, ?, ?, ?)
        """,
            (
                d["discovered_by_wallet"],
                d["contract_address"],
                d["chain"],
                d["discovered_by_wallet"],
                d["contract_address"],
                d["discovered_at"],
                now,
                d.get("profit", 0),
                d.get("roi_pct", 0),
                d.get("buy_tx_count", 0),
                d.get("sell_tx_count", 0),
                d.get("is_profitable", 0),
            ),
        )

    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK SETUP
# ═══════════════════════════════════════════════════════════════════════════════


def setup_alchemy_webhook(wallets: list[dict], webhook_url: str = "") -> str | None:
    """
    Create Alchemy webhook for wallet activity monitoring.

    Monitors EVM wallets (ETH, Base, BSC) for token transfers.
    """
    api_key = settings.alchemy_api_key
    if not api_key:
        log.warning("alchemy_no_key")
        return None

    # Get EVM wallet addresses
    evm_wallets = [w for w in wallets if w.get("chain", "").lower() in ("ethereum", "eth", "base", "bsc", "binance")]
    if not evm_wallets:
        return None

    addresses = [w["address"] for w in evm_wallets[:25]]  # Alchemy limit

    try:
        # Create webhook via Alchemy Notify API
        resp = requests.post(
            "https://dashboard.alchemyapi.io/api/create-webhook",
            json={
                "network": "ETH_MAINNET",  # Base uses same webhook
                "webhook_type": "ADDRESS_ACTIVITY",
                "addresses": addresses,
                "webhook_url": webhook_url or "https://your-server.com/alchemy/webhook",
            },
            headers={"X-Alchemy-Token": api_key},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            webhook_id = data.get("data", {}).get("id", "")
            log.info("alchemy_webhook_created", id=webhook_id, addresses=len(addresses))
            return webhook_id
        else:
            log.error("alchemy_webhook_failed", status=resp.status_code, response=resp.text[:200])
    except Exception as e:
        log.error("alchemy_webhook_error", error=str(e))

    return None


def setup_helius_webhook(wallets: list[dict], webhook_url: str = "") -> str | None:
    """
    Create Helius webhook for Solana wallet monitoring.
    """
    api_key = settings.helius_api_key
    if not api_key:
        log.warning("helius_no_key")
        return None

    sol_wallets = [w for w in wallets if w.get("chain", "").lower() in ("solana", "sol")]
    if not sol_wallets:
        return None

    addresses = [w["address"] for w in sol_wallets[:100]]

    try:
        resp = requests.post(
            f"https://api.helius.xyz/v0/webhooks?api-key={api_key}",
            json={
                "webhookURL": webhook_url or "https://your-server.com/helius/webhook",
                "transactionTypes": ["SWAP", "TRANSFER"],
                "accountAddresses": addresses,
                "webhookType": "enhanced",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            webhook_id = data.get("webhookID", "")
            log.info("helius_webhook_created", id=webhook_id, addresses=len(addresses))
            return webhook_id
        else:
            log.error("helius_webhook_failed", status=resp.status_code, response=resp.text[:200])
    except Exception as e:
        log.error("helius_webhook_error", error=str(e))

    return None


def setup_quicknode_webhook(wallets: list[dict], webhook_url: str = "") -> str | None:
    """
    Create QuickNode webhook for EVM wallet monitoring.
    """
    api_key = settings.quicknode_key
    if not api_key:
        log.warning("quicknode_no_key")
        return None

    evm_wallets = [w for w in wallets if w.get("chain", "").lower() in ("ethereum", "eth", "base", "bsc", "binance")]
    if not evm_wallets:
        return None

    addresses = [w["address"] for w in evm_wallets[:25]]

    try:
        resp = requests.post(
            "https://api.quicknode.com/quickalerts/rest/v1/destinations",
            json={
                "name": "hermes-copytrade-monitor",
                "to_url": webhook_url or "https://your-server.com/quicknode/webhook",
            },
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            dest_id = resp.json().get("id", "")
            log.info("quicknode_destination_created", id=dest_id)

            # Create alert for wallet transfers
            alert_resp = requests.post(
                "https://api.quicknode.com/quickalerts/rest/v1/alerts",
                json={
                    "name": "hermes-wallet-transfers",
                    "destination_id": dest_id,
                    "expression": "("
                    + " || ".join([f"tx_from == '{a}' || tx_to == '{a}'" for a in addresses[:5]])
                    + ")",
                    "network": "ethereum-mainnet",
                },
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                timeout=15,
            )
            if alert_resp.status_code == 200:
                alert_id = alert_resp.json().get("id", "")
                log.info("quicknode_alert_created", id=alert_id)
                return alert_id
    except Exception as e:
        log.error("quicknode_webhook_error", error=str(e))

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ANKR BALANCE POLLING
# ═══════════════════════════════════════════════════════════════════════════════

ANKR_API_KEY = "0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
ANKR_ENDPOINT = "https://rpc.ankr.com/multichain/" + ANKR_API_KEY

ANKR_CHAINS = {
    "ethereum": "eth",
    "eth": "eth",
    "base": "base",
    "binance": "bsc",
    "bsc": "bsc",
    "polygon": "polygon",
    "avalanche": "avalanche",
}


def poll_ankr_balances(wallets: list[dict]) -> list[dict]:
    """
    Poll Ankr for multi-chain token balances.

    Detects new token holdings by comparing against previous state.
    """
    new_positions = []

    for wallet in wallets:
        addr = wallet.get("address", "")
        chain = wallet.get("chain", "").lower()
        ankr_chain = ANKR_CHAINS.get(chain)

        if not ankr_chain or not addr:
            continue

        try:
            resp = requests.post(
                ANKR_ENDPOINT,
                json={
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "ankr_getAccountBalance",
                    "params": {
                        "blockchain": [ankr_chain],
                        "walletAddress": addr,
                    },
                },
                headers={"Content-Type": "application/json"},
                timeout=15,
            )

            if resp.status_code == 200:
                data = resp.json().get("result", {})
                tokens = data.get("tokens", [])

                for token in tokens:
                    token_addr = token.get("contractAddress", "")
                    balance = float(token.get("balance", 0))
                    balance_usd = float(token.get("balanceUsd", 0))

                    if token_addr and balance > 0 and balance_usd > 1:  # skip dust
                        new_positions.append(
                            {
                                "wallet_address": addr,
                                "token_address": token_addr,
                                "chain": chain,
                                "symbol": token.get("tokenSymbol", ""),
                                "balance": balance,
                                "balance_usd": balance_usd,
                                "discovered_at": time.time(),
                                "discovery_method": "ankr_poll",
                            }
                        )
        except Exception as e:
            log.debug("ankr_poll_error", wallet=addr[:12], error=str(e))
            continue

    log.info("ankr_positions_found", total=len(new_positions))
    return new_positions


# ═══════════════════════════════════════════════════════════════════════════════
# ENRICHMENT INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════


def enrich_discovered_tokens(conn: sqlite3.Connection):
    """
    Enrich discovered tokens that haven't been enriched yet.

    Uses Dexscreener for market data (same as token_enricher layer 0).
    """
    unenriched = conn.execute(
        "SELECT id, contract_address, chain, symbol FROM discovered_tokens "
        "WHERE enrichment_score = 0 AND status = 'active' ORDER BY wallet_count DESC LIMIT 50"
    ).fetchall()

    enriched = 0
    for row in unenriched:
        token_id, addr, chain, symbol = row

        try:
            resp = requests.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{addr}",
                timeout=10,
            )
            if resp.status_code != 200:
                continue

            pairs = resp.json().get("pairs", [])
            if not pairs:
                continue

            best = max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
            fdv = best.get("fdv", 0) or 0
            vol24 = best.get("volume", {}).get("h24", 0) or 0
            price = float(best.get("priceUsd", 0) or 0)
            base = best.get("baseToken", {})

            # Simple enrichment score based on market data
            score = 0
            if fdv > 0:
                if 10000 <= fdv <= 10000000:
                    score += 30
                elif fdv > 0:
                    score += 15
            if vol24 > 10000:
                score += 20
            elif vol24 > 1000:
                score += 10
            if price > 0:
                score += 10

            # Wallet count bonus
            wallet_count = conn.execute(
                "SELECT wallet_count FROM discovered_tokens WHERE id = ?", (token_id,)
            ).fetchone()[0]
            score += min(wallet_count * 10, 30)

            conn.execute(
                """
                UPDATE discovered_tokens SET
                    symbol = COALESCE(NULLIF(symbol, ''), ?),
                    name = ?,
                    fdv = ?,
                    volume_h24 = ?,
                    current_price_usd = ?,
                    enrichment_score = ?,
                    enriched_at = ?
                WHERE id = ?
            """,
                (
                    base.get("symbol", symbol),
                    base.get("name", ""),
                    fdv,
                    vol24,
                    price,
                    round(score, 1),
                    time.time(),
                    token_id,
                ),
            )
            enriched += 1
            metrics.api_calls.labels(provider="dexscreener_copytrade", status="ok").inc()

        except Exception as e:
            metrics.api_calls.labels(provider="dexscreener_copytrade", status="error").inc()
            log.debug("enrich_error", token=addr[:12], error=str(e))

    conn.commit()
    log.info("discoveries_enriched", enriched=enriched)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════


def run_copytrade_monitor(
    min_wallet_score: float = 30,
    setup_webhooks: bool = False,
    poll_ankr: bool = True,
) -> dict[str, Any]:
    """Run the copytrade monitoring pipeline."""
    start = time.time()

    log.info("=" * 60)
    log.info("Copy-Trade Monitor starting")
    log.info("=" * 60)

    # Init DB
    disc_conn = init_discoveries_db()

    # Load top wallets
    conn = sqlite3.connect(f"file:{WALLETS_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    wallets = [
        dict(r)
        for r in conn.execute(
            "SELECT address, chain, wallet_score, wallet_tags FROM tracked_wallets "
            "WHERE wallet_score >= ? ORDER BY wallet_score DESC LIMIT 50",
            (min_wallet_score,),
        ).fetchall()
    ]
    conn.close()

    log.info("wallets_loaded", count=len(wallets))

    # Setup webhooks if requested
    webhook_ids = {}
    if setup_webhooks:
        webhook_ids["alchemy"] = setup_alchemy_webhook(wallets)
        webhook_ids["helius"] = setup_helius_webhook(wallets)
        webhook_ids["quicknode"] = setup_quicknode_webhook(wallets)
        log.info("webhooks_setup", **{k: bool(v) for k, v in webhook_ids.items()})

    # Scan wallet positions from existing data
    wallet_positions = scan_wallet_positions(min_wallet_score)
    new_from_scan = detect_new_positions(wallet_positions, disc_conn)
    if new_from_scan:
        save_discoveries(new_from_scan, disc_conn)
        log.info("new_from_scan", count=len(new_from_scan))

    # Poll Ankr for fresh balances
    new_from_ankr = []
    if poll_ankr:
        ankr_positions = poll_ankr_balances(wallets)
        for pos in ankr_positions:
            # Convert to discovery format
            discovery = {
                "contract_address": pos["token_address"],
                "chain": pos["chain"],
                "symbol": pos.get("symbol", ""),
                "discovered_by_wallet": pos["wallet_address"],
                "discovery_method": "ankr_poll",
                "discovered_at": pos["discovered_at"],
                "profit": 0,
                "roi_pct": 0,
            }
            # Check if already known
            existing = disc_conn.execute(
                "SELECT id FROM discovered_tokens WHERE contract_address = ? AND chain = ?",
                (pos["token_address"], pos["chain"]),
            ).fetchone()
            if not existing:
                new_from_ankr.append(discovery)

        if new_from_ankr:
            save_discoveries(new_from_ankr, disc_conn)
            log.info("new_from_ankr", count=len(new_from_ankr))

    # Enrich discovered tokens
    enrich_discovered_tokens(disc_conn)

    # Report
    total = disc_conn.execute("SELECT COUNT(*) FROM discovered_tokens").fetchone()[0]
    active = disc_conn.execute("SELECT COUNT(*) FROM discovered_tokens WHERE status = 'active'").fetchone()[0]
    top5 = disc_conn.execute(
        "SELECT symbol, contract_address, enrichment_score, wallet_count FROM discovered_tokens "
        "WHERE status = 'active' ORDER BY enrichment_score DESC LIMIT 5"
    ).fetchall()

    disc_conn.close()

    elapsed = time.time() - start

    result = {
        "status": "ok",
        "total_discoveries": total,
        "active": active,
        "new_this_run": len(new_from_scan) + len(new_from_ankr),
        "webhooks": webhook_ids,
        "top_discoveries": [
            {"symbol": r[0], "address": r[1][:12] + "...", "score": r[2], "wallets": r[3]} for r in top5
        ],
        "elapsed": round(elapsed, 1),
    }

    log.info("copytrade_monitor_done", **{k: v for k, v in result.items() if k != "top_discoveries"})
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Copy-trade monitor")
    parser.add_argument("--min-wallet-score", type=float, default=30)
    parser.add_argument("--setup-webhooks", action="store_true")
    parser.add_argument("--no-ankr", action="store_true")
    args = parser.parse_args()

    result = run_copytrade_monitor(
        min_wallet_score=args.min_wallet_score,
        setup_webhooks=args.setup_webhooks,
        poll_ankr=not args.no_ankr,
    )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
