#!/usr/bin/env python3
import argparse
import json
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path('/home/terexitarius/.hermes/data/central_contracts.db')
OUT_PATH = Path('/home/terexitarius/.hermes/data/smart_money/pre180_watchlist.json')
DEX = 'https://api.dexscreener.com/latest/dex/tokens/'


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={'User-Agent': 'hermes-pre180-scanner/production'})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode('utf-8', errors='ignore'))


def pair_age_h(pair):
    ts = pair.get('pairCreatedAt')
    if not ts:
        return None
    return (time.time() * 1000 - ts) / 1000 / 3600


def best_pair(pairs, chain):
    target = {'ethereum': 'ethereum', 'base': 'base', 'solana': 'solana'}.get(chain, chain)
    cands = [p for p in pairs if (p.get('chainId') or '').lower() == target] or pairs
    cands.sort(key=lambda p: float(p.get('liquidity', {}).get('usd') or 0), reverse=True)
    return cands[0] if cands else None


def pre180_score(row):
    score = 0.0
    pc24 = row['pc24h_pct']
    pc1 = row['pc1h_pct']
    pc5 = row['pc5m_pct']

    # momentum progression (before 180)
    if 10 <= pc24 < 180:
        score += min(16, (pc24 / 180) * 16)
    if pc1 >= -6:
        score += (3 if pc1 > 0 else 0) + min(14, max(pc1, 0) / 25 * 14)
    if pc5 >= -1:
        score += (2 if pc5 > 0 else 0) + min(8, max(pc5, 0) / 6 * 8)

    # participation + tradability
    score += min(14, row['vol1h_usd'] / 75000 * 14)
    score += min(8, row['tx1h'] / 150 * 8)
    score += min(8, max(0, row['buy_ratio_1h'] - 0.48) / 0.52 * 8)
    score += min(14, row['liq_usd'] / 180000 * 14)

    # age sweet spot
    age = row['age_h']
    if age is not None:
        if 1 <= age <= 72:
            score += 8
        elif age <= 240:
            score += 4

    # social recurrence
    if row['mentions'] >= 2:
        score += 6

    return round(min(100, score), 1)


def ensure_pre180_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pre180_daily_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            run_ts REAL NOT NULL,
            scanned_contracts INTEGER NOT NULL,
            pre180_candidates INTEGER NOT NULL,
            high_quality_candidates INTEGER NOT NULL,
            min_score REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pre180_daily_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            run_ts REAL NOT NULL,
            score REAL NOT NULL,
            chain TEXT NOT NULL,
            contract TEXT NOT NULL,
            symbol TEXT,
            dex TEXT,
            liq_usd REAL,
            vol1h_usd REAL,
            vol24h_usd REAL,
            pc5m_pct REAL,
            pc1h_pct REAL,
            pc24h_pct REAL,
            buy_ratio_1h REAL,
            tx1h INTEGER,
            age_h REAL,
            mentions INTEGER,
            risk_flags TEXT,
            last_seen_utc TEXT,
            UNIQUE(run_date, chain, contract)
        )
        """
    )
    conn.commit()


def persist_daily_snapshot(payload, min_score: float):
    run_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    run_ts = time.time()

    selected = [
        row for row in payload['all_top25']
        if row['pre180_score'] >= min_score
    ]

    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_pre180_tables(conn)

        conn.execute(
            """
            INSERT INTO pre180_daily_runs (
                run_date, run_ts, scanned_contracts,
                pre180_candidates, high_quality_candidates, min_score
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_date,
                run_ts,
                int(payload['scanned_contracts']),
                int(payload['pre180_candidates']),
                int(payload['high_quality_candidates']),
                float(min_score),
            ),
        )

        rows = [
            (
                run_date,
                run_ts,
                float(r['pre180_score']),
                r['chain'],
                r['contract'],
                r.get('symbol'),
                r.get('dex'),
                float(r.get('liq_usd') or 0),
                float(r.get('vol1h_usd') or 0),
                float(r.get('vol24h_usd') or 0),
                float(r.get('pc5m_pct') or 0),
                float(r.get('pc1h_pct') or 0),
                float(r.get('pc24h_pct') or 0),
                float(r.get('buy_ratio_1h') or 0),
                int(r.get('tx1h') or 0),
                float(r.get('age_h') or 0),
                int(r.get('mentions') or 0),
                json.dumps(r.get('risk_flags', [])),
                r.get('last_seen_utc'),
            )
            for r in selected
        ]

        conn.executemany(
            """
            INSERT INTO pre180_daily_candidates (
                run_date, run_ts, score, chain, contract, symbol, dex,
                liq_usd, vol1h_usd, vol24h_usd,
                pc5m_pct, pc1h_pct, pc24h_pct,
                buy_ratio_1h, tx1h, age_h, mentions,
                risk_flags, last_seen_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_date, chain, contract) DO UPDATE SET
                run_ts = excluded.run_ts,
                score = excluded.score,
                symbol = excluded.symbol,
                dex = excluded.dex,
                liq_usd = excluded.liq_usd,
                vol1h_usd = excluded.vol1h_usd,
                vol24h_usd = excluded.vol24h_usd,
                pc5m_pct = excluded.pc5m_pct,
                pc1h_pct = excluded.pc1h_pct,
                pc24h_pct = excluded.pc24h_pct,
                buy_ratio_1h = excluded.buy_ratio_1h,
                tx1h = excluded.tx1h,
                age_h = excluded.age_h,
                mentions = excluded.mentions,
                risk_flags = excluded.risk_flags,
                last_seen_utc = excluded.last_seen_utc
            """,
            rows,
        )

        conn.commit()
        return len(rows)
    finally:
        conn.close()


def run(limit=240, persist_db=False, min_score=35.0):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        'select chain, contract_address, mentions, last_seen_at from telegram_contracts_unique order by last_seen_at desc limit ?',
        (limit,),
    )
    contracts = cur.fetchall()
    conn.close()

    rows = []
    for chain, addr, mentions, last_seen in contracts:
        try:
            pairs = (fetch_json(DEX + addr).get('pairs') or [])
            pair = best_pair(pairs, chain)
            if not pair:
                continue

            pc = pair.get('priceChange', {}) or {}
            vol = pair.get('volume', {}) or {}
            tx = pair.get('txns', {}) or {}
            h1 = tx.get('h1', {}) or {}

            buys1 = float(h1.get('buys') or 0)
            sells1 = float(h1.get('sells') or 0)
            tx1 = buys1 + sells1
            buy_ratio1 = (buys1 / tx1) if tx1 > 0 else 0

            row = {
                'chain': chain,
                'contract': addr,
                'symbol': (pair.get('baseToken') or {}).get('symbol'),
                'dex': pair.get('dexId'),
                'liq_usd': float(pair.get('liquidity', {}).get('usd') or 0),
                'vol1h_usd': float(vol.get('h1') or 0),
                'vol24h_usd': float(vol.get('h24') or 0),
                'pc5m_pct': float(pc.get('m5') or 0),
                'pc1h_pct': float(pc.get('h1') or 0),
                'pc24h_pct': float(pc.get('h24') or 0),
                'buy_ratio_1h': buy_ratio1,
                'tx1h': int(tx1),
                'age_h': pair_age_h(pair),
                'mentions': int(mentions),
                'last_seen_utc': datetime.fromtimestamp(last_seen, timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            }

            # pre-180 universe: not already exploded and not dust
            if row['pc24h_pct'] >= 180 or row['liq_usd'] < 10000:
                continue

            row['pre180_score'] = pre180_score(row)

            risk = []
            if row['liq_usd'] < 30000:
                risk.append('thin_liquidity')
            if row['buy_ratio_1h'] < 0.52:
                risk.append('weak_buy_pressure')
            if row['age_h'] is not None and row['age_h'] < 3:
                risk.append('very_new')
            if row['pc24h_pct'] > 120:
                risk.append('near_180_zone')
            row['risk_flags'] = risk

            rows.append(row)
        except Exception:
            continue

    rows.sort(key=lambda r: (r['pre180_score'], r['vol1h_usd']), reverse=True)

    high_quality = [
        r for r in rows
        if r['liq_usd'] >= 50000 and r['vol1h_usd'] >= 8000 and r['pc24h_pct'] >= 10 and 'weak_buy_pressure' not in r['risk_flags']
    ]

    payload = {
        'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'scanned_contracts': len(contracts),
        'pre180_candidates': len(rows),
        'high_quality_candidates': len(high_quality),
        'high_quality_top10': high_quality[:10],
        'all_top25': rows[:25],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))

    persisted_rows = 0
    if persist_db:
        persisted_rows = persist_daily_snapshot(payload, min_score=min_score)
        payload['persisted_daily_rows'] = persisted_rows
        OUT_PATH.write_text(json.dumps(payload, indent=2))

    print(json.dumps(payload, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Pre-180 momentum scanner')
    parser.add_argument('--limit', type=int, default=240)
    parser.add_argument('--persist-db', action='store_true', help='Persist daily snapshot to central SQLite DB')
    parser.add_argument('--min-score', type=float, default=35.0, help='Minimum pre180 score to persist in daily snapshot')
    args = parser.parse_args()

    run(limit=args.limit, persist_db=args.persist_db, min_score=args.min_score)


if __name__ == '__main__':
    main()
