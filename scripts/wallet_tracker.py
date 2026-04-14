#!/usr/bin/env python3
"""
Wallet Tracker v2 - Enrich wallet data from top-scoring tokens.

Discovers and scores smart money wallets by scanning top holders across
multiple winning tokens. Cross-token presence = win rate signal.

Scoring (0-100):
  PNL (0-30), ROI (0-25), Win Rate (0-25), Entry Timing (0-10), Trade Count (0-10)

Usage:
  python3 wallet_tracker.py                    # normal run
  python3 wallet_tracker.py --min-score 30     # only enrich from tokens scoring >30
  python3 wallet_tracker.py --max-tokens 20    # limit token scans
  python3 wallet_tracker.py --dry-run          # don't write to DB
"""

import os
import sys
import json
import time
import sqlite3
import subprocess
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = Path.home() / '.hermes' / 'data' / 'central_contracts.db'
WALLETS_DB = Path.home() / '.hermes' / 'data' / 'wallet_tracker.db'
TOP_TOKENS_PATH = Path.home() / '.hermes' / 'data' / 'token_screener' / 'top100.json'
LOG_FILE = Path.home() / '.hermes' / 'logs' / 'wallet_tracker.log'

GMGN_CLI = str(Path.home() / '.hermes' / 'gmgn-cli' / 'dist' / 'index.js')
GMGN_API_KEY = os.getenv('GMGN_API_KEY', '')
HOLDERS_PER_TOKEN = 15  # how many holders to fetch per token
CHAIN_MAP = {'solana': 'sol', 'sol': 'sol', 'base': 'base',
             'ethereum': 'base', 'eth': 'base', 'binance': 'bsc', 'bsc': 'bsc'}

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
WALLETS_DB.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('wallet_tracker')

# ── GMGN CLI (node resolution) ─────────────────────────────────────────────
_NODE_BIN = None

def find_node() -> str:
    global _NODE_BIN
    if _NODE_BIN:
        return _NODE_BIN
    node = shutil.which('node')
    if node:
        _NODE_BIN = node
        return node
    for c in [str(Path.home() / '.local' / 'bin' / 'node'), '/usr/local/bin/node', '/usr/bin/node']:
        if Path(c).is_file():
            _NODE_BIN = c
            return c
    _NODE_BIN = 'node'
    return 'node'

def gmgn_cmd(args: list) -> Optional[Any]:
    """Run gmgn-cli and parse JSON."""
    try:
        env = {**os.environ, 'GMGN_API_KEY': GMGN_API_KEY}
        r = subprocess.run(
            [find_node(), GMGN_CLI] + args,
            capture_output=True, text=True, timeout=30, env=env
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout.strip())
    except Exception:
        pass
    return None


# ── Database ────────────────────────────────────────────────────────────────

def init_wallet_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(WALLETS_DB), timeout=30)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tracked_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            chain TEXT NOT NULL,
            discovered_at REAL NOT NULL,
            last_updated REAL,
            
            -- Source info
            source_tokens TEXT DEFAULT '',
            source_token_count INTEGER DEFAULT 0,
            
            -- Scoring
            wallet_score REAL DEFAULT 0,
            
            -- Per-token metrics (from GMGN token holders)
            realized_pnl REAL,
            unrealized_pnl REAL,
            total_profit REAL,
            avg_roi REAL,
            total_trades INTEGER,
            buy_count INTEGER,
            sell_count INTEGER,
            avg_cost REAL,
            entry_timing_score REAL,
            
            -- Cross-token metrics
            win_rate REAL,
            tokens_profitable INTEGER DEFAULT 0,
            tokens_total INTEGER DEFAULT 0,
            
            -- Social
            smart_money_tag TEXT,
            wallet_tags TEXT,
            twitter_username TEXT,
            
            -- Activity
            first_seen_at REAL,
            last_active_at REAL,
            
            UNIQUE(chain, address)
        );

        CREATE TABLE IF NOT EXISTS wallet_token_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            token_address TEXT NOT NULL,
            token_symbol TEXT,
            
            -- Per-token data from GMGN
            profit REAL,
            profit_change REAL,
            realized_profit REAL,
            unrealized_profit REAL,
            buy_tx_count INTEGER,
            sell_tx_count INTEGER,
            avg_cost REAL,
            start_holding_at REAL,
            end_holding_at REAL,
            is_profitable INTEGER,
            
            discovered_at REAL NOT NULL,
            
            UNIQUE(wallet_address, token_address)
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

        CREATE INDEX IF NOT EXISTS idx_wallets_score ON tracked_wallets(wallet_score DESC);
        CREATE INDEX IF NOT EXISTS idx_wallets_winrate ON tracked_wallets(win_rate DESC);
        CREATE INDEX IF NOT EXISTS idx_entries_wallet ON wallet_token_entries(wallet_address);
        CREATE INDEX IF NOT EXISTS idx_entries_token ON wallet_token_entries(token_address);
    """)
    conn.commit()
    return conn


# ── Wallet Scoring ──────────────────────────────────────────────────────────

def score_wallet(
    realized_pnl: float,
    avg_roi: float,
    win_rate: float,
    entry_timing: float,
    total_trades: int,
) -> float:
    """
    Compute wallet quality score (0-100).
    
    PNL (0-30):       >$100K=30, >$50K=25, >$10K=20, >$1K=10, >$0=5
    ROI (0-25):       >500%=25, >200%=20, >100%=15, >50%=10, >0=5
    Win Rate (0-25):  >80%=25, >65%=20, >50%=15, >35%=10
    Entry (0-10):     <0.1=10, <0.3=7, <0.5=5 (0=at launch=best)
    Trades (0-10):    >50=10, >20=7, >10=5
    """
    score = 0.0

    # PNL
    if realized_pnl > 100000: score += 30
    elif realized_pnl > 50000: score += 25
    elif realized_pnl > 10000: score += 20
    elif realized_pnl > 1000: score += 10
    elif realized_pnl > 0: score += 5

    # ROI (avg_roi is a multiplier, e.g. 6.6 = 660%)
    roi_pct = avg_roi * 100 if avg_roi else 0
    if roi_pct > 500: score += 25
    elif roi_pct > 200: score += 20
    elif roi_pct > 100: score += 15
    elif roi_pct > 50: score += 10
    elif roi_pct > 0: score += 5

    # Win rate
    if win_rate > 0.80: score += 25
    elif win_rate > 0.65: score += 20
    elif win_rate > 0.50: score += 15
    elif win_rate > 0.35: score += 10

    # Entry timing (0-1 normalized, 0=early=best)
    if entry_timing < 0.1: score += 10
    elif entry_timing < 0.3: score += 7
    elif entry_timing < 0.5: score += 5

    # Trade count
    if total_trades > 50: score += 10
    elif total_trades > 20: score += 7
    elif total_trades > 10: score += 5

    return min(100, round(score, 1))


# ── Discovery ───────────────────────────────────────────────────────────────

def get_holders_for_token(chain: str, address: str, limit: int = HOLDERS_PER_TOKEN) -> List[dict]:
    """Get top holders/traders for a token via GMGN."""
    gmgn_chain = CHAIN_MAP.get(chain.lower())
    if not gmgn_chain:
        return []

    data = gmgn_cmd([
        'token', 'holders', '--chain', gmgn_chain,
        '--address', address, '--limit', str(limit), '--raw'
    ])
    if not data:
        return []

    return data if isinstance(data, list) else data.get('list', [])


def enrich_wallets_from_tokens(
    conn: sqlite3.Connection,
    tokens: List[dict],
    min_token_score: float = 30,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Scan top holders from multiple tokens, merge wallet data.
    A wallet appearing in N tokens with M profitable = win_rate = M/N.
    """
    cursor = conn.cursor()
    now = time.time()

    # Collect all wallet appearances across tokens
    # wallet_addr -> [{token, symbol, profit, roi, trades, entry_time, ...}]
    wallet_appearances: Dict[str, List[dict]] = {}
    tokens_scanned = 0
    holders_found = 0

    for token_info in tokens:
        chain = token_info.get('chain', '')
        addr = token_info.get('contract_address', '')
        sym = token_info.get('symbol', '?')
        score = token_info.get('score', 0)

        if score < min_token_score:
            continue

        log.info(f"  Scanning {sym} (score={score:.1f})...")
        holders = get_holders_for_token(chain, addr)
        tokens_scanned += 1

        for h in holders:
            w = h.get('address', '')
            if not w:
                continue

            profit = h.get('profit', 0) or 0
            roi = h.get('profit_change', 0) or 0
            realized = h.get('realized_profit', 0) or 0
            unrealized = h.get('unrealized_profit', 0) or 0
            buy_count = h.get('buy_tx_count_cur', 0) or 0
            sell_count = h.get('sell_tx_count_cur', 0) or 0
            start_at = h.get('start_holding_at')
            tag = h.get('wallet_tag_v2', '')
            tags = h.get('tags', [])
            twitter = h.get('twitter_username', '')

            is_profitable = 1 if profit > 0 else 0
            holders_found += 1

            entry = {
                'chain': chain,
                'token_address': addr,
                'token_symbol': sym,
                'profit': profit,
                'profit_change': roi,
                'realized_profit': realized,
                'unrealized_profit': unrealized,
                'buy_tx_count': buy_count,
                'sell_tx_count': sell_count,
                'total_trades': buy_count + sell_count,
                'avg_cost': h.get('avg_cost'),
                'start_holding_at': start_at,
                'end_holding_at': h.get('end_holding_at'),
                'is_profitable': is_profitable,
                'tag': tag,
                'tags': tags,
                'twitter': twitter,
            }

            if w not in wallet_appearances:
                wallet_appearances[w] = []
            wallet_appearances[w].append(entry)

    log.info(f"  Scanned {tokens_scanned} tokens, found {holders_found} holder entries, {len(wallet_appearances)} unique wallets")

    # Aggregate per wallet and save
    wallets_updated = 0
    wallets_new = 0

    for wallet_addr, appearances in wallet_appearances.items():
        chain = appearances[0]['chain']  # all should be same chain
        total_profit = sum(a['profit'] for a in appearances)
        total_realized = sum(a['realized_profit'] for a in appearances)
        total_unrealized = sum(a['unrealized_profit'] for a in appearances)
        total_trades = sum(a['total_trades'] for a in appearances)
        total_buys = sum(a['buy_tx_count'] for a in appearances)
        total_sells = sum(a['sell_tx_count'] for a in appearances)

        # ROI: average across tokens (weighted by trade count)
        rois = [a['profit_change'] for a in appearances if a['profit_change'] and a['profit_change'] > 0]
        avg_roi = sum(rois) / len(rois) if rois else 0

        # Win rate
        profitable = sum(a['is_profitable'] for a in appearances)
        win_rate = profitable / len(appearances) if appearances else 0

        # Entry timing: average normalized position (0=early, 1=late)
        # Lower start_holding_at relative to token launch = earlier entry
        entry_scores = []
        for a in appearances:
            if a['start_holding_at'] and a['total_trades'] > 0:
                # Simple heuristic: if they have sells, they've been active a while
                entry_scores.append(0.2 if a['sell_tx_count'] > 0 else 0.1)
        avg_entry = sum(entry_scores) / len(entry_scores) if entry_scores else 0.5

        # Best tag across all appearances
        all_tags = set()
        for a in appearances:
            if a['tag']:
                all_tags.add(a['tag'])
            for t in (a['tags'] or []):
                all_tags.add(t)
        best_tag = min(all_tags, key=lambda t: int(t.replace('TOP', '99')) if t.startswith('TOP') else 99) if all_tags else ''

        # Twitter (first non-empty)
        twitter = next((a['twitter'] for a in appearances if a['twitter']), '')

        # Source tokens
        source_tokens = ','.join(set(a['token_symbol'] for a in appearances))

        # Score
        wallet_score = score_wallet(
            realized_pnl=total_realized or total_profit,
            avg_roi=avg_roi,
            win_rate=win_rate,
            entry_timing=avg_entry,
            total_trades=total_trades,
        )

        if dry_run:
            continue

        # Upsert wallet
        cursor.execute("""
            INSERT INTO tracked_wallets 
                (address, chain, discovered_at, last_updated,
                 source_tokens, source_token_count,
                 wallet_score, realized_pnl, unrealized_pnl, total_profit,
                 avg_roi, total_trades, buy_count, sell_count,
                 entry_timing_score, win_rate,
                 tokens_profitable, tokens_total,
                 smart_money_tag, wallet_tags, twitter_username,
                 first_seen_at, last_active_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chain, address) DO UPDATE SET
                last_updated = excluded.last_updated,
                source_tokens = excluded.source_tokens,
                source_token_count = excluded.source_token_count,
                wallet_score = excluded.wallet_score,
                realized_pnl = excluded.realized_pnl,
                unrealized_pnl = excluded.unrealized_pnl,
                total_profit = excluded.total_profit,
                avg_roi = excluded.avg_roi,
                total_trades = excluded.total_trades,
                buy_count = excluded.buy_count,
                sell_count = excluded.sell_count,
                entry_timing_score = excluded.entry_timing_score,
                win_rate = excluded.win_rate,
                tokens_profitable = excluded.tokens_profitable,
                tokens_total = excluded.tokens_total,
                smart_money_tag = excluded.smart_money_tag,
                wallet_tags = excluded.wallet_tags,
                twitter_username = excluded.twitter_username,
                last_active_at = excluded.last_active_at
        """, (
            wallet_addr, chain, now, now,
            source_tokens, len(appearances),
            wallet_score, total_realized, total_unrealized, total_profit,
            avg_roi, total_trades, total_buys, total_sells,
            avg_entry, win_rate,
            profitable, len(appearances),
            best_tag, ','.join(all_tags), twitter,
            appearances[0].get('start_holding_at') or now,
            now,
        ))

        # Check if new
        cursor.execute("SELECT id FROM tracked_wallets WHERE chain = ? AND address = ?", (chain, wallet_addr))
        if cursor.fetchone():
            wallets_updated += 1
        else:
            wallets_new += 1

        # Save per-token entries
        for a in appearances:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO wallet_token_entries
                        (wallet_address, chain, token_address, token_symbol,
                         profit, profit_change, realized_profit, unrealized_profit,
                         buy_tx_count, sell_tx_count, avg_cost,
                         start_holding_at, end_holding_at, is_profitable,
                         discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    wallet_addr, chain, a['token_address'], a['token_symbol'],
                    a['profit'], a['profit_change'], a['realized_profit'], a['unrealized_profit'],
                    a['buy_tx_count'], a['sell_tx_count'], a['avg_cost'],
                    a['start_holding_at'], a['end_holding_at'], a['is_profitable'],
                    now,
                ))
            except Exception:
                pass

    conn.commit()
    return {
        'tokens_scanned': tokens_scanned,
        'holders_found': holders_found,
        'unique_wallets': len(wallet_appearances),
        'wallets_new': wallets_new,
        'wallets_updated': wallets_updated,
    }


# ── Reporting ───────────────────────────────────────────────────────────────

def report(conn: sqlite3.Connection, limit: int = 20):
    """Print top wallets with full metrics."""
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT address, chain, wallet_score, realized_pnl, avg_roi, 
               win_rate, total_trades, tokens_profitable, tokens_total,
               smart_money_tag, source_tokens, twitter_username
        FROM tracked_wallets
        WHERE wallet_score > 0
        ORDER BY wallet_score DESC
        LIMIT {limit}
    """)

    print(f"\n{'='*80}")
    print(f"TOP {limit} WALLETS BY SCORE")
    print(f"{'='*80}")
    print(f"{'Score':>6} {'PnL':>12} {'ROI':>8} {'WinRate':>8} {'Trades':>7} {'Tokens':>7} {'Tag':>6} {'Wallet'}")
    print(f"{'-'*6} {'-'*12} {'-'*8} {'-'*8} {'-'*7} {'-'*7} {'-'*6} {'-'*30}")

    for r in cursor.fetchall():
        addr, chain, score, pnl, roi, wr, trades, prof, total, tag, tokens, tw = r
        pnl_str = f"${pnl or 0:>11,.0f}" if pnl else "      $0"
        roi_str = f"{(roi or 0)*100:>6.0f}%" if roi else "    -%"
        wr_str = f"{(wr or 0)*100:>6.0f}%" if wr else "    -%"
        trades_str = f"{trades or 0:>6}"
        tokens_str = f"{prof or 0}/{total or 0}"
        print(f"{score:>6.1f} {pnl_str} {roi_str} {wr_str} {trades_str} {tokens_str:>7} {tag or '-':>6} {addr[:30]}...")

    # Stats
    cursor.execute("SELECT count(*), avg(wallet_score), max(wallet_score), count(CASE WHEN win_rate > 0.5 THEN 1 END) FROM tracked_wallets")
    total, avg_s, max_s, high_wr = cursor.fetchone()
    print(f"\nTotal: {total} wallets | Avg score: {avg_s:.1f} | Max: {max_s:.1f} | Win rate >50%: {high_wr}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Wallet tracker')
    parser.add_argument('--min-score', type=float, default=30)
    parser.add_argument('--max-tokens', type=int, default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("Wallet Tracker starting")
    log.info(f"Min token score: {args.min_score}")
    log.info("=" * 60)

    # Load top tokens
    if not Path(TOP_TOKENS_PATH).exists():
        log.warning(f"No {TOP_TOKENS_PATH} found. Run token_enricher.py first.")
        return 1

    with open(TOP_TOKENS_PATH) as f:
        data = json.load(f)
    tokens = data.get('tokens', [])

    if args.max_tokens:
        tokens = tokens[:args.max_tokens]

    log.info(f"Loaded {len(tokens)} tokens from enricher output")

    # Init DB and enrich
    conn = init_wallet_db()
    start = time.time()

    result = enrich_wallets_from_tokens(
        conn, tokens,
        min_token_score=args.min_score,
        dry_run=args.dry_run,
    )

    elapsed = time.time() - start
    log.info(f"Done in {elapsed:.1f}s: {json.dumps(result)}")

    # Report
    report(conn)
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
