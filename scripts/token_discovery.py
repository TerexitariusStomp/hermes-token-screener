#!/usr/bin/env python3
"""
Token Discovery - Pull trending/new tokens from multiple sources into the contract DB.

Sources (all free, no auth required):
  1. Dexscreener Boosted (top promoted tokens)
  2. Dexscreener Profiles (newly listed tokens)
  3. Dexscreener Search (keyword-based, configurable)
  4. CoinGecko Trending (top trending coins with contract addresses)

This supplements the Telegram scraper — provides tokens that haven't been
called in Telegram yet but are gaining attention on DEX platforms.

Usage:
  python3 token_discovery.py                   # normal run
  python3 token_discovery.py --chains solana   # only Solana
  python3 token_discovery.py --keywords pepe,doge,trump  # search terms
"""

import os
import sys
import json
import time
import sqlite3
import logging
import requests
from pathlib import Path
from typing import List, Dict, Tuple, Set

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = Path.home() / '.hermes' / 'data' / 'central_contracts.db'
LOG_FILE = Path.home() / '.hermes' / 'logs' / 'token_discovery.log'

# Chains to accept (others filtered out)
DEFAULT_CHAINS = {'solana', 'ethereum', 'base', 'binance-smart-chain'}

# Dexscreener search keywords (meme coin trends)
DEFAULT_KEYWORDS = [
    'pepe', 'doge', 'trump', 'maga', 'elon', 'frog', 'cat', 'dog',
    'bear', 'bull', 'moon', 'ai', 'agent', 'meme', 'inu', 'cat',
    'pump', 'based', 'degen', 'wen', 'bonk', 'wif',
]

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('token_discovery')

# ── Database ────────────────────────────────────────────────────────────────

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


def insert_discovery(conn, chain: str, address: str, source: str, 
                     description: str = '', observed_at: float = None) -> bool:
    """Insert a discovered token address. Returns True if new."""
    now = time.time()
    ts = observed_at or now
    chan_str = f"discovery:{source}"
    
    try:
        # Insert into calls table
        msg_id = int(now * 1000) + hash(address) % 10000
        conn.execute("""
            INSERT INTO telegram_contract_calls
                (channel_id, message_id, chain, contract_address, raw_address,
                 address_source, message_text, observed_at, session_source, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (chan_str, msg_id, chain, address, address,
              source, description[:500], ts, 'token_discovery', now))

        # Upsert into unique table
        conn.execute("""
            INSERT INTO telegram_contracts_unique
                (chain, contract_address, first_seen_at, last_seen_at, mentions,
                 last_channel_id, last_message_id, last_raw_address, last_source,
                 last_message_text, channel_count, channels_seen)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(chain, contract_address) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                mentions = CASE
                    WHEN last_source != excluded.last_source THEN mentions + 1
                    ELSE mentions
                END,
                last_source = excluded.last_source,
                last_message_text = excluded.last_message_text,
                channel_count = CASE
                    WHEN ',' || channels_seen || ',' LIKE '%,' || ? || ',%'
                    THEN channel_count
                    ELSE channel_count + 1
                END,
                channels_seen = CASE
                    WHEN channels_seen = '' OR channels_seen IS NULL THEN ?
                    WHEN ',' || channels_seen || ',' LIKE '%,' || ? || ',%'
                    THEN channels_seen
                    ELSE channels_seen || ',' || ?
                END
        """, (chain, address, ts, ts, chan_str, msg_id, address, source,
              description[:500], chan_str,
              chan_str, chan_str, chan_str, chan_str))
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        log.debug(f"Insert error for {chain}:{address[:20]}: {e}")
        return False


# ── Sources ─────────────────────────────────────────────────────────────────

def fetch_dexscreener_boosted() -> List[Tuple[str, str, str]]:
    """Fetch top boosted tokens from Dexscreener (free)."""
    try:
        r = requests.get('https://api.dexscreener.com/token-boosts/top/v1', timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        results = []
        for t in data:
            chain = t.get('chainId', '')
            addr = t.get('tokenAddress', '')
            if chain and addr:
                results.append((chain, addr, 'dexscreener_boost'))
        return results
    except Exception as e:
        log.warning(f"Dexscreener boosted error: {e}")
        return []


def fetch_dexscreener_profiles() -> List[Tuple[str, str, str]]:
    """Fetch latest token profiles from Dexscreener (free)."""
    try:
        r = requests.get('https://api.dexscreener.com/token-profiles/latest/v1', timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        results = []
        for t in data:
            chain = t.get('chainId', '')
            addr = t.get('tokenAddress', '')
            desc = t.get('description', '')[:200]
            if chain and addr:
                results.append((chain, addr, f'dexscreener_profile:{desc}'))
        return results
    except Exception as e:
        log.warning(f"Dexscreener profiles error: {e}")
        return []


def fetch_dexscreener_search(keywords: List[str]) -> List[Tuple[str, str, str]]:
    """Search Dexscreener by keywords (free)."""
    results = []
    for kw in keywords[:10]:  # limit to 10 searches
        try:
            time.sleep(1.5)  # rate limit
            r = requests.get(f'https://api.dexscreener.com/latest/dex/search?q={kw}', timeout=10)
            if r.status_code != 200:
                continue
            pairs = r.json().get('pairs', [])
            for p in pairs[:5]:  # top 5 per keyword
                chain = p.get('chainId', '')
                addr = p.get('baseToken', {}).get('address', '')
                sym = p.get('baseToken', {}).get('symbol', '?')
                vol = p.get('volume', {}).get('h24', 0) or 0
                if chain and addr and vol > 5000:  # filter low volume
                    results.append((chain, addr, f'dexscreener_search:{kw}:{sym}'))
        except Exception as e:
            log.debug(f"Search '{kw}' error: {e}")
    return results


def fetch_coingecko_trending() -> List[Tuple[str, str, str]]:
    """Fetch trending coins from CoinGecko with contract addresses (free)."""
    try:
        r = requests.get('https://api.coingecko.com/api/v3/search/trending', timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        results = []
        chain_map = {
            'solana': 'solana', 'ethereum': 'ethereum',
            'binance-smart-chain': 'binance', 'base': 'base',
        }
        for coin in data.get('coins', []):
            item = coin.get('item', {})
            platforms = item.get('data', {}).get('platforms', {})
            sym = item.get('symbol', '?')
            name = item.get('name', '?')
            for platform, addr in platforms.items():
                if addr and platform in chain_map:
                    chain = chain_map[platform]
                    results.append((chain, addr, f'coingecko_trending:{sym}:{name}'))
        return results
    except Exception as e:
        log.warning(f"CoinGecko trending error: {e}")
        return []


# ── Main ────────────────────────────────────────────────────────────────────

def run_discovery(chains: Set[str] = None, keywords: List[str] = None):
    """Run all discovery sources and insert into DB."""
    chains = chains or DEFAULT_CHAINS
    keywords = keywords or DEFAULT_KEYWORDS
    
    conn = get_db()
    ensure_tables(conn)
    
    all_tokens = []
    
    # 1. Dexscreener boosted
    log.info("Fetching Dexscreener boosted tokens...")
    boosted = fetch_dexscreener_boosted()
    log.info(f"  Found {len(boosted)} boosted tokens")
    all_tokens.extend(boosted)
    
    # 2. Dexscreener profiles
    log.info("Fetching Dexscreener token profiles...")
    profiles = fetch_dexscreener_profiles()
    log.info(f"  Found {len(profiles)} token profiles")
    all_tokens.extend(profiles)
    
    # 3. Dexscreener search
    log.info(f"Searching Dexscreener for {len(keywords)} keywords...")
    search = fetch_dexscreener_search(keywords)
    log.info(f"  Found {len(search)} tokens from search")
    all_tokens.extend(search)
    
    # 4. CoinGecko trending
    log.info("Fetching CoinGecko trending...")
    trending = fetch_coingecko_trending()
    log.info(f"  Found {len(trending)} trending coins")
    all_tokens.extend(trending)
    
    # Filter by chain and deduplicate
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
    
    # Insert into DB
    new_count = 0
    for chain, addr, source in unique:
        if insert_discovery(conn, chain, addr, source):
            new_count += 1
    
    conn.commit()
    conn.close()
    
    log.info(f"Inserted {new_count} new tokens into DB")
    
    # Summary
    sources = {}
    for _, _, src in unique:
        base = src.split(':')[0]
        sources[base] = sources.get(base, 0) + 1
    
    return {
        'status': 'ok',
        'total_discovered': len(unique),
        'new_inserted': new_count,
        'sources': sources,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Token discovery from DEX platforms')
    parser.add_argument('--chains', type=str, default=None, help='Comma-separated chains')
    parser.add_argument('--keywords', type=str, default=None, help='Comma-separated search keywords')
    args = parser.parse_args()
    
    chains = set(args.chains.split(',')) if args.chains else None
    keywords = args.keywords.split(',') if args.keywords else None
    
    log.info("=" * 60)
    log.info("Token Discovery starting")
    log.info("=" * 60)
    
    start = time.time()
    result = run_discovery(chains, keywords)
    elapsed = time.time() - start
    
    log.info(f"Done in {elapsed:.1f}s: {json.dumps(result)}")
    return 0 if result.get('status') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
