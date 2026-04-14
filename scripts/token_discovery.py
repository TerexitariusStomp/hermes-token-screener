#!/usr/bin/env python3
"""
Token Discovery - Pull trending/new tokens from Dexscreener into the contract DB.

Sources (all free, no auth):
  1. Dexscreener Boosted (top promoted tokens)
  2. Dexscreener Profiles (newly listed tokens)

Usage:
  python3 token_discovery.py                   # normal run
  python3 token_discovery.py --chains solana   # only Solana
"""

import json
import time
import sqlite3
import sys
import requests
from pathlib import Path
from typing import List, Tuple, Set

from hermes_screener.config import settings
from hermes_screener.logging import get_logger, log_duration
from hermes_screener.metrics import metrics, start_metrics_server

DB_PATH = settings.db_path
DEFAULT_CHAINS = {'solana', 'ethereum', 'base', 'binance-smart-chain'}

log = get_logger("token_discovery")
start_metrics_server()


def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS telegram_contract_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            chain TEXT,
            contract_address TEXT NOT NULL,
            raw_address TEXT,
            address_source TEXT,
            message_text TEXT,
            observed_at REAL,
            session_source TEXT,
            inserted_at REAL NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_calls_msg_contract
            ON telegram_contract_calls(message_id, contract_address);

        CREATE TABLE IF NOT EXISTS telegram_contracts_unique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain TEXT NOT NULL,
            contract_address TEXT NOT NULL,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            mentions INTEGER NOT NULL,
            last_channel_id TEXT,
            last_message_id INTEGER,
            last_raw_address TEXT,
            last_source TEXT,
            last_message_text TEXT,
            channel_count INTEGER NOT NULL DEFAULT 0,
            channels_seen TEXT DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_chain_addr
            ON telegram_contracts_unique(chain, contract_address);
    """)
    conn.commit()


def insert_discovery(conn, chain: str, address: str, source: str, description: str = '') -> bool:
    now = time.time()
    chan_str = f"discovery:{source}"
    try:
        msg_id = int(now * 1000) + hash(address) % 10000
        conn.execute("""
            INSERT INTO telegram_contract_calls
                (channel_id, message_id, chain, contract_address, raw_address,
                 address_source, message_text, observed_at, session_source, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (chan_str, msg_id, chain, address, address, source, description[:500], now, 'token_discovery', now))

        conn.execute("""
            INSERT INTO telegram_contracts_unique
                (chain, contract_address, first_seen_at, last_seen_at, mentions,
                 last_channel_id, last_message_id, last_raw_address, last_source,
                 last_message_text, channel_count, channels_seen)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(chain, contract_address) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                last_source = excluded.last_source,
                channel_count = CASE
                    WHEN ',' || channels_seen || ',' LIKE '%,' || ? || ',%'
                    THEN channel_count ELSE channel_count + 1 END,
                channels_seen = CASE
                    WHEN channels_seen = '' OR channels_seen IS NULL THEN ?
                    WHEN ',' || channels_seen || ',' LIKE '%,' || ? || ',%'
                    THEN channels_seen ELSE channels_seen || ',' || ? END
        """, (chain, address, now, now, chan_str, msg_id, address, source,
              description[:500], chan_str, chan_str, chan_str, chan_str, chan_str))
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception:
        return False


def fetch_dexscreener_boosted() -> List[Tuple[str, str, str]]:
    try:
        r = requests.get('https://api.dexscreener.com/token-boosts/top/v1', timeout=15)
        if r.status_code != 200:
            return []
        return [(t.get('chainId', ''), t.get('tokenAddress', ''), 'dexscreener_boost')
                for t in r.json() if t.get('chainId') and t.get('tokenAddress')]
    except Exception:
        return []


def fetch_dexscreener_profiles() -> List[Tuple[str, str, str]]:
    try:
        r = requests.get('https://api.dexscreener.com/token-profiles/latest/v1', timeout=15)
        if r.status_code != 200:
            return []
        return [(t.get('chainId', ''), t.get('tokenAddress', ''),
                 f"dexscreener_profile:{t.get('description', '')[:100]}")
                for t in r.json() if t.get('chainId') and t.get('tokenAddress')]
    except Exception:
        return []


def run_discovery(chains: Set[str] = None):
    chains = chains or DEFAULT_CHAINS
    conn = get_db()
    ensure_tables(conn)

    all_tokens = []

    log.info("Fetching Dexscreener boosted tokens...")
    boosted = fetch_dexscreener_boosted()
    log.info(f"  Found {len(boosted)} boosted tokens")
    all_tokens.extend(boosted)

    log.info("Fetching Dexscreener token profiles...")
    profiles = fetch_dexscreener_profiles()
    log.info(f"  Found {len(profiles)} token profiles")
    all_tokens.extend(profiles)

    seen = set()
    unique = []
    for chain, addr, source in all_tokens:
        if chain not in chains:
            continue
        key = f"{chain}:{addr}"
        if key not in seen:
            seen.add(key)
            unique.append((chain, addr, source))

    log.info(f"Total unique tokens after filter: {len(unique)}")

    new_count = sum(1 for chain, addr, source in unique if insert_discovery(conn, chain, addr, source))
    conn.commit()
    conn.close()

    log.info(f"Inserted {new_count} new tokens into DB")
    return {'status': 'ok', 'total_discovered': len(unique), 'new_inserted': new_count}


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Token discovery from DEX platforms')
    parser.add_argument('--chains', type=str, default=None, help='Comma-separated chains')
    args = parser.parse_args()
    chains = set(args.chains.split(',')) if args.chains else None

    log.info("=" * 60)
    log.info("Token Discovery starting")
    log.info("=" * 60)

    start = time.time()
    result = run_discovery(chains)
    elapsed = time.time() - start
    log.info(f"Done in {elapsed:.1f}s: {json.dumps(result)}")
    return 0 if result.get('status') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
