#!/usr/bin/env python3
"""
Database Maintenance - Prune tokens and wallets to keep only top performers.

Runs daily to:
  1. Remove tokens that scored < threshold for 7+ days
  2. Keep only top 1000 tokens by channel_count + mentions
  3. Keep only top 1000 wallets by wallet_score
  4. Clean orphaned wallet entries (tokens no longer in DB)

Usage:
  python3 db_maintenance.py                   # normal run
  python3 db_maintenance.py --max-tokens 1000  # override limit
  python3 db_maintenance.py --dry-run          # don't actually delete
"""

import os
import sys
import json
import time
import sqlite3
import logging
from pathlib import Path

DB_PATH = Path.home() / '.hermes' / 'data' / 'central_contracts.db'
WALLETS_DB = Path.home() / '.hermes' / 'data' / 'wallet_tracker.db'
TOP_TOKENS_PATH = Path.home() / '.hermes' / 'data' / 'token_screener' / 'top100.json'
LOG_FILE = Path.home() / '.hermes' / 'logs' / 'db_maintenance.log'

MAX_TOKENS = 1000
MAX_WALLETS = 1000
MIN_TOKEN_AGE_DAYS = 7  # don't delete tokens younger than this

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('db_maintenance')


def prune_contracts(max_tokens: int, dry_run: bool = False):
    """Keep only top N contracts by channel_count * mentions."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    c = conn.cursor()

    # Count current
    c.execute("SELECT count(*) FROM telegram_contracts_unique")
    before = c.fetchone()[0]

    if before <= max_tokens:
        log.info(f"Contracts: {before}/{max_tokens} — no pruning needed")
        conn.close()
        return 0

    # Find contracts to keep (top by channel_count * mentions)
    cutoff_time = time.time() - (MIN_TOKEN_AGE_DAYS * 86400)
    c.execute("""
        SELECT chain, contract_address FROM telegram_contracts_unique
        WHERE first_seen_at < ?
        ORDER BY (channel_count * mentions) DESC
        LIMIT -1 OFFSET ?
    """, (cutoff_time, max_tokens))
    to_delete = c.fetchall()

    if not to_delete:
        log.info(f"Contracts: {before} — all within age limit, no pruning")
        conn.close()
        return 0

    log.info(f"Contracts: {before} → pruning {len(to_delete)} old/low-scoring")

    if not dry_run:
        for chain, addr in to_delete:
            c.execute("DELETE FROM telegram_contract_calls WHERE chain = ? AND contract_address = ?", (chain, addr))
            c.execute("DELETE FROM telegram_contracts_unique WHERE chain = ? AND contract_address = ?", (chain, addr))
        conn.commit()

    c.execute("SELECT count(*) FROM telegram_contracts_unique")
    after = c.fetchone()[0]
    conn.close()

    log.info(f"  Contracts: {before} → {after} (removed {before - after})")
    return before - after


def prune_wallets(max_wallets: int, dry_run: bool = False):
    """Keep only top N wallets by wallet_score."""
    if not WALLETS_DB.exists():
        log.info("Wallet DB doesn't exist yet")
        return 0

    conn = sqlite3.connect(str(WALLETS_DB), timeout=30)
    c = conn.cursor()

    c.execute("SELECT count(*) FROM tracked_wallets")
    before = c.fetchone()[0]

    if before <= max_wallets:
        log.info(f"Wallets: {before}/{max_wallets} — no pruning needed")
        conn.close()
        return 0

    # Find wallets to keep (top by score)
    c.execute("""
        SELECT address, chain FROM tracked_wallets
        ORDER BY wallet_score DESC
        LIMIT -1 OFFSET ?
    """, (max_wallets,))
    to_delete = c.fetchall()

    log.info(f"Wallets: {before} → pruning {len(to_delete)} low-scoring")

    if not dry_run:
        for addr, chain in to_delete:
            c.execute("DELETE FROM wallet_token_entries WHERE wallet_address = ?", (addr,))
            c.execute("DELETE FROM tracked_wallets WHERE address = ? AND chain = ?", (addr, chain))
        conn.commit()

    c.execute("SELECT count(*) FROM tracked_wallets")
    after = c.fetchone()[0]
    conn.close()

    log.info(f"  Wallets: {before} → {after} (removed {before - after})")
    return before - after


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Database maintenance')
    parser.add_argument('--max-tokens', type=int, default=MAX_TOKENS)
    parser.add_argument('--max-wallets', type=int, default=MAX_WALLETS)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("DB Maintenance starting")
    if args.dry_run:
        log.info("*** DRY RUN ***")
    log.info("=" * 60)

    start = time.time()
    removed_contracts = prune_contracts(args.max_tokens, args.dry_run)
    removed_wallets = prune_wallets(args.max_wallets, args.dry_run)
    elapsed = time.time() - start

    log.info(f"Done in {elapsed:.1f}s: contracts removed={removed_contracts}, wallets removed={removed_wallets}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
