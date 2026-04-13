#!/usr/bin/env python3
"""
Wallet Tracker - Track top wallets from winning tokens.

For tokens with top buy signals, identifies the best-performing wallets
and monitors them for future buys.

Wallet scoring:
  - Realized PNL
  - Average ROI per trade
  - Win rate (profitable trades %)
  - Entry timing (how early relative to launch)
  - Position sizing
  - Hold time before selling

Monitoring:
  - Alchemy webhooks (EVM chains)
  - QuickNode webhooks (EVM chains)
  - Helius webhooks (Solana)
"""

import os
import json
import time
import sqlite3
import subprocess
import requests
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')

log = logging.getLogger('wallet_tracker')

DB_PATH = Path.home() / '.hermes' / 'data' / 'central_contracts.db'
WALLETS_DB = Path.home() / '.hermes' / 'data' / 'wallet_tracker.db'
WALLETS_DB.parent.mkdir(parents=True, exist_ok=True)

GMGN_CLI = str(Path.home() / '.hermes' / 'gmgn-cli' / 'dist' / 'index.js')
GMGN_API_KEY = os.getenv('GMGN_API_KEY', '')
ALCHEMY_KEY = os.getenv('ALCHEMY_API_KEY', '')
QUICKNODE_KEY = os.getenv('QUICKNODE_KEY', '')
HELIUS_KEY = os.getenv('HELIUS_API_KEY', '')


def init_wallet_db():
    """Initialize wallet tracking database."""
    conn = sqlite3.connect(str(WALLETS_DB))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tracked_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            chain TEXT NOT NULL,
            source_token TEXT,
            source_token_symbol TEXT,
            discovered_at REAL NOT NULL,
            wallet_score REAL DEFAULT 0,
            realized_pnl REAL,
            avg_roi REAL,
            win_rate REAL,
            avg_entry_timing REAL,
            total_trades INTEGER,
            smart_money_tag TEXT,
            last_active REAL,
            UNIQUE(chain, address)
        );

        CREATE TABLE IF NOT EXISTS wallet_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            token_address TEXT NOT NULL,
            token_symbol TEXT,
            action TEXT,
            amount_usd REAL,
            price REAL,
            timestamp REAL,
            tx_hash TEXT,
            pnl_usd REAL,
            UNIQUE(tx_hash, token_address)
        );

        CREATE TABLE IF NOT EXISTS wallet_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            token_address TEXT NOT NULL,
            token_symbol TEXT,
            alert_type TEXT,
            details TEXT,
            created_at REAL NOT NULL,
            notified INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_wallets_chain ON tracked_wallets(chain);
        CREATE INDEX IF NOT EXISTS idx_wallets_score ON tracked_wallets(wallet_score DESC);
        CREATE INDEX IF NOT EXISTS idx_trades_wallet ON wallet_trades(wallet_address);
        CREATE INDEX IF NOT EXISTS idx_alerts_notified ON wallet_alerts(notified);
    """)
    conn.commit()
    return conn


def score_wallet(pnl: float, roi: float, win_rate: float,
                 entry_timing: float, total_trades: int) -> float:
    """
    Compute wallet quality score (0-100).
    
    - Realized PNL (0-30): >$100K=30, >$10K=20, >$1K=10
    - Average ROI (0-25): >500%=25, >200%=20, >100%=15, >50%=10
    - Win rate (0-25): >80%=25, >65%=20, >50%=15
    - Entry timing (0-10): earlier = better (0-1 normalized)
    - Trade count (0-10): >50=10, >20=7, >10=5
    """
    score = 0

    # PNL
    if pnl > 100000: score += 30
    elif pnl > 10000: score += 20
    elif pnl > 1000: score += 10
    elif pnl > 0: score += 5

    # ROI
    if roi > 500: score += 25
    elif roi > 200: score += 20
    elif roi > 100: score += 15
    elif roi > 50: score += 10
    elif roi > 0: score += 5

    # Win rate
    if win_rate > 0.80: score += 25
    elif win_rate > 0.65: score += 20
    elif win_rate > 0.50: score += 15
    elif win_rate > 0.35: score += 10

    # Entry timing (0-1 where 0 = bought at launch = best)
    if entry_timing < 0.1: score += 10
    elif entry_timing < 0.3: score += 7
    elif entry_timing < 0.5: score += 5

    # Trade count
    if total_trades > 50: score += 10
    elif total_trades > 20: score += 7
    elif total_trades > 10: score += 5

    return min(100, score)


def get_top_wallets_from_token(chain: str, token: str, limit: int = 20) -> List[dict]:
    """Get top wallets for a token using GMGN CLI."""
    gmgn_chain = {'solana': 'sol', 'sol': 'sol', 'base': 'base', 'bsc': 'bsc'}.get(chain.lower())
    if not gmgn_chain or not GMGN_API_KEY:
        return []

    try:
        env = {**os.environ, 'GMGN_API_KEY': GMGN_API_KEY}
        result = subprocess.run(
            ['node', GMGN_CLI, 'token', 'holders',
             '--chain', gmgn_chain, '--address', token,
             '--limit', str(limit), '--json'],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            return data.get('list', [])
    except Exception as e:
        log.error(f"GMGN holders error: {e}")
    return []


def analyze_wallet(chain: str, address: str) -> Dict[str, Any]:
    """Get wallet performance data from GMGN."""
    gmgn_chain = {'solana': 'sol', 'sol': 'sol', 'base': 'base', 'bsc': 'bsc'}.get(chain.lower())
    if not gmgn_chain or not GMGN_API_KEY:
        return {}

    try:
        env = {**os.environ, 'GMGN_API_KEY': GMGN_API_KEY}
        result = subprocess.run(
            ['node', GMGN_CLI, 'wallet', 'detail',
             '--chain', gmgn_chain, '--address', address, '--json'],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except Exception as e:
        log.error(f"GMGN wallet error: {e}")
    return {}


def discover_wallets_from_top_tokens(conn: sqlite3.Connection, top_tokens: List[dict]):
    """For each top token, extract and score the best wallets."""
    cursor = conn.cursor()
    discovered = 0

    for token_info in top_tokens:
        chain = token_info.get('chain', '')
        addr = token_info.get('contract_address', '')
        symbol = token_info.get('symbol', '?')
        score = token_info.get('score', 0)

        # Only track wallets from high-scoring tokens
        if score < 50:
            continue

        log.info(f"Extracting wallets from {symbol} (score={score:.1f})...")
        holders = get_top_wallets_from_token(chain, addr, limit=10)

        for holder in holders:
            wallet_addr = holder.get('address', '')
            if not wallet_addr:
                continue

            # Check if already tracked
            cursor.execute(
                "SELECT id FROM tracked_wallets WHERE chain = ? AND address = ?",
                (chain, wallet_addr)
            )
            if cursor.fetchone():
                continue

            # Calculate wallet metrics from holder data
            pnl = holder.get('profit', 0) or 0
            profit_change = holder.get('profit_change', 0) or 0
            is_smart = holder.get('wallet_tag_v2', '') in ('SMART', 'DEGEN', 'TOP1', 'TOP10')

            # Score the wallet
            wallet_score = score_wallet(
                pnl=pnl,
                roi=profit_change * 100 if profit_change else 0,
                win_rate=0,  # Need wallet detail API
                entry_timing=0,
                total_trades=0
            )

            # Insert
            cursor.execute("""
                INSERT OR IGNORE INTO tracked_wallets
                    (address, chain, source_token, source_token_symbol,
                     discovered_at, wallet_score, realized_pnl, smart_money_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (wallet_addr, chain, addr, symbol,
                  time.time(), wallet_score, pnl,
                  holder.get('wallet_tag_v2', '')))
            discovered += 1

    conn.commit()
    log.info(f"Discovered {discovered} new wallets")
    return discovered


def get_all_tracked_wallets(conn: sqlite3.Connection) -> List[dict]:
    """Get all tracked wallets sorted by score."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT address, chain, wallet_score, source_token_symbol,
               realized_pnl, smart_money_tag, last_active
        FROM tracked_wallets
        WHERE wallet_score > 20
        ORDER BY wallet_score DESC
        LIMIT 100
    """)
    columns = ['address', 'chain', 'score', 'source_token',
               'pnl', 'tag', 'last_active']
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ── Webhook Setup ───────────────────────────────────────────────────────────

def setup_alchemy_webhook(webhook_url: str, addresses: List[str]) -> dict:
    """Set up Alchemy webhook for EVM wallet monitoring."""
    if not ALCHEMY_KEY:
        return {}

    try:
        r = requests.post(
            'https://dashboard.alchemyapi.io/api/webhook',
            headers={'X-Alchemy-Token': ALCHEMY_KEY},
            json={
                'webhook_type': 'ADDRESS_ACTIVITY',
                'webhook_url': webhook_url,
                'addresses': addresses[:100],  # max 100
                'network': 'BASE_MAINNET',
            },
            timeout=15
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.error(f"Alchemy webhook error: {e}")
    return {}


def setup_helius_webhook(webhook_url: str, addresses: List[str]) -> dict:
    """Set up Helius webhook for Solana wallet monitoring."""
    if not HELIUS_KEY:
        return {}

    try:
        r = requests.post(
            f'https://api.helius.xyz/v0/webhooks?api-key={HELIUS_KEY}',
            json={
                'webhookURL': webhook_url,
                'transactionTypes': ['TRANSFER'],
                'accountAddresses': addresses[:100],
                'webhookType': 'enhanced',
            },
            timeout=15
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.error(f"Helius webhook error: {e}")
    return {}


# ── Main ────────────────────────────────────────────────────────────────────

def run_wallet_discovery(top_tokens_path: str = None):
    """Main wallet discovery from top tokens."""
    conn = init_wallet_db()

    # Load top tokens from screener output
    if not top_tokens_path:
        top_tokens_path = str(Path.home() / '.hermes' / 'data' / 'token_screener' / 'top100.json')

    if not Path(top_tokens_path).exists():
        log.warning("No top100.json found. Run token_screener.py first.")
        return

    with open(top_tokens_path) as f:
        data = json.load(f)
    tokens = data.get('tokens', [])

    log.info(f"Processing {len(tokens)} tokens for wallet discovery...")

    # Discover wallets from top tokens
    discover_wallets_from_top_tokens(conn, tokens)

    # Report
    wallets = get_all_tracked_wallets(conn)
    log.info(f"Total tracked wallets: {len(wallets)}")
    for w in wallets[:10]:
        log.info(f"  {w['chain']}:{w['address'][:20]}... score={w['score']:.0f} "
                 f"pnl=${w['pnl']:,.0f} tag={w['tag']}")

    conn.close()
    return wallets


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s')
    run_wallet_discovery()
