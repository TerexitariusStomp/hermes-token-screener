#!/usr/bin/env python3
"""
Token Enricher - Unified multi-source enrichment pipeline with resilient try/bypass.

Consolidates all data sources into one self-contained script:
  Layer 0: Dexscreener (core market data)         [REQUIRED - pipeline stops if this fails]
  Layer 1: Surf (market context + social)          [optional]
  Layer 2: GoPlus (EVM security)                   [optional]
  Layer 3: RugCheck (Solana security)              [optional]
  Layer 4: Etherscan (contract verification)       [optional]
  Layer 5: De.Fi (security analysis)               [optional]
  Layer 6: Derived (computed security signals)     [optional, no API needed]
  Layer 7: CoinGecko (market data + listings)      [optional]
  Layer 8: GMGN (dev conviction + smart money)     [optional]
  Layer 9: Social (Telegram DB + composite score)  [optional, no API needed]

Design: Each enricher is tried. If it fails, its fields are skipped but the
pipeline continues. Status of each layer is logged and reported in output.

Usage:
  python3 token_enricher.py                     # normal run
  python3 token_enricher.py --max-tokens 50     # limit enrichment
  python3 token_enricher.py --min-channels 3    # higher threshold

Output: ~/.hermes/data/token_screener/top100.json
"""

import json
import time
import sqlite3
import subprocess
import math
import shutil
import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta

import requests

from hermes_screener.config import settings
from hermes_screener.logging import get_logger, log_duration
from hermes_screener.metrics import metrics, start_metrics_server

# ── Config (from centralized settings) ───────────────────────────────────────
DB_PATH = settings.db_path
OUTPUT_PATH = settings.output_path
TOP_N = settings.top_n
MAX_ENRICH = settings.max_enrich
MIN_CHANNEL_COUNT = settings.min_channels

# Scoring weights
W_CHANNEL = settings.w_channel
W_FRESHNESS = settings.w_freshness
W_LOW_FDV = settings.w_low_fdv
W_VOLUME = settings.w_volume
W_TXNS = settings.w_txns
W_MOMENTUM = settings.w_momentum

SELL_RATIO_THRESHOLD = settings.sell_ratio_threshold
STAGNANT_VOLUME_RATIO = settings.stagnant_volume_ratio
NO_ACTIVITY_HOURS = settings.no_activity_hours

# API keys (empty string = layer gracefully skipped)
COINGECKO_API_KEY = settings.coingecko_api_key
ETHERSCAN_API_KEY = settings.etherscan_api_key
DEFI_API_KEY = settings.defi_api_key
RUGCHECK_API_KEY = settings.rugcheck_api_key
GMGN_API_KEY = settings.gmgn_api_key
SURF_API_KEY = settings.surf_api_key
ZERION_API_KEY = settings.zerion_api_key

# ── Logging + Metrics ────────────────────────────────────────────────────────
log = get_logger("token_enricher")
start_metrics_server()



# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_token(token: dict) -> Tuple[float, List[str], List[str]]:
    dex = token.get('dex', {})
    score = 0.0
    positives = []
    negatives = []

    # ── DISQUALIFIERS (return 0 immediately) ──
    if token.get('gmgn_honeypot'):
        return 0, [], ["HONEYPOT"]
    if token.get('goplus_is_honeypot'):
        return 0, [], ["HONEYPOT (GoPlus)"]
    if token.get('rugcheck_rugged'):
        return 0, [], ["RUGGED"]
    if token.get('defi_scammed'):
        return 0, [], ["SCAMMED"]
    if token.get('derived_possible_rug'):
        return 0, [], ["POSSIBLE RUG"]
    if token.get('derived_massive_dump'):
        return 0, [], ["MASSIVE DUMP"]

    pc_h1 = dex.get('price_change_h1')
    pc_h6 = dex.get('price_change_h6')
    pc_h24 = dex.get('price_change_h24')
    fdv = dex.get('fdv') or dex.get('market_cap') or 0
    vol_h24 = dex.get('volume_h24', 0) or 0
    vol_h1 = dex.get('volume_h1', 0) or 0
    age_hours = dex.get('age_hours')
    channel_count = token.get('channel_count', 0)
    mentions = token.get('mentions', 0)
    smart = token.get('gmgn_smart_wallets', 0)

    # ── 1. FDV/VOLUME RATIO (0-25) ──
    # Low FDV + high volume = high opportunity
    if fdv > 0 and vol_h24 > 0:
        vol_fdv_ratio = vol_h24 / fdv
        if vol_fdv_ratio > 2: fdv_vol_score = 25      # FDV $100K, vol $200K+
        elif vol_fdv_ratio > 1: fdv_vol_score = 22
        elif vol_fdv_ratio > 0.5: fdv_vol_score = 18
        elif vol_fdv_ratio > 0.2: fdv_vol_score = 14
        elif vol_fdv_ratio > 0.05: fdv_vol_score = 10
        else: fdv_vol_score = 5
        score += fdv_vol_score
    elif fdv > 0:
        # Low FDV alone is good
        if fdv < 50_000: score += 12
        elif fdv < 200_000: score += 9
        elif fdv < 1_000_000: score += 6
        elif fdv < 5_000_000: score += 3

    # ── 2. CHANNELS + MENTIONS (0-20) ──
    # More channels mentioning = more legitimate discovery
    if channel_count >= 10: score += 12
    elif channel_count >= 5: score += 9
    elif channel_count >= 3: score += 6
    elif channel_count >= 2: score += 3

    if mentions >= 10: score += 8
    elif mentions >= 5: score += 6
    elif mentions >= 3: score += 4
    elif mentions >= 1: score += 2

    # ── 3. SMART WALLETS (0-15) ──
    if smart >= 50: score += 15
    elif smart >= 30: score += 12
    elif smart >= 20: score += 10
    elif smart >= 10: score += 7
    elif smart >= 5: score += 4
    elif smart >= 1: score += 2

    # ── 4. DEV HOLDING (0-10) ──
    if token.get('gmgn_dev_hold'):
        score += 10
    dev_rate = token.get('gmgn_dev_team_hold_rate')
    if dev_rate is not None and dev_rate > 0.05:
        score += 3

    # ── 5. SOCIAL SIGNALS (0-10) ──
    tw_sent = token.get('tw_sentiment_score', 0) or 0
    social = token.get('social_score', 0) or 0
    if tw_sent > 70: score += 5
    elif tw_sent > 50: score += 3
    if social > 20: score += 5
    elif social > 10: score += 3
    elif social > 5: score += 1

    # ── 6. PRICE MOMENTUM (0-10) ──
    # Positive % on ALL timeframes = strong bullish
    all_positive = True
    if pc_h1 is not None:
        if pc_h1 > 0: score += 3
        else: all_positive = False
    if pc_h6 is not None:
        if pc_h6 > 0: score += 3
        else: all_positive = False
    if pc_h24 is not None:
        if pc_h24 > 0: score += 2
        else: all_positive = False
    if all_positive and pc_h1 and pc_h6 and pc_h24:
        score += 2  # bonus for all-positive

    # ── 7. AGE PENALTY (older = harder to move) ──
    if age_hours is not None:
        if age_hours > 720: score *= 0.5        # >30 days
        elif age_hours > 168: score *= 0.7      # >7 days
        elif age_hours > 72: score *= 0.85      # >3 days

    # ── STEEP DECLINE PENALTIES (>20% loss on any timeframe) ──
    if pc_h1 is not None:
        if pc_h1 < -60:
            score *= 0.1
            negatives.append(f"CRASH h1 ({pc_h1:+.0f}%)")
        elif pc_h1 < -40:
            score *= 0.2
            negatives.append(f"steep decline h1 ({pc_h1:+.0f}%)")
        elif pc_h1 < -20:
            score *= 0.5
            negatives.append(f"decline h1 ({pc_h1:+.0f}%)")

    if pc_h6 is not None:
        if pc_h6 < -70:
            score *= 0.1
            negatives.append(f"DEAD h6 ({pc_h6:+.0f}%)")
        elif pc_h6 < -50:
            score *= 0.2
            negatives.append(f"crashed h6 ({pc_h6:+.0f}%)")
        elif pc_h6 < -20:
            score *= 0.5
            negatives.append(f"declining h6 ({pc_h6:+.0f}%)")

    if pc_h24 is not None:
        if pc_h24 < -80:
            score *= 0.1
            negatives.append(f"DEAD h24 ({pc_h24:+.0f}%)")
        elif pc_h24 < -50:
            score *= 0.3
            negatives.append(f"collapsed h24 ({pc_h24:+.0f}%)")
        elif pc_h24 < -20:
            score *= 0.6
            negatives.append(f"down h24 ({pc_h24:+.0f}%)")

    # Death spiral
    if vol_h24 > 0 and vol_h1 < vol_h24 * 0.005:
        if pc_h6 is not None and pc_h6 < -10:
            score *= 0.3
            negatives.append("death spiral")

    # ── MULTIPLIERS (positive only) ──
    if token.get('etherscan_verified'):
        score *= 1.15

    if token.get('gmgn_renounced_mint') is True:
        score *= 1.10
    elif token.get('gmgn_renounced_mint') is False:
        score *= 0.3
        negatives.append("mint not renounced")

    if token.get('rugcheck_freeze_renounced') is False:
        score *= 0.5
        negatives.append("freeze not renounced")

    if token.get('gmgn_burn_status') == 'burn':
        score *= 1.15
        if "burned" not in str(positives).lower():
            positives.append("burned")

    if token.get('gmgn_cto_flag'):
        score *= 1.10
        positives.append("CTO")

    if token.get('gmgn_dev_token_farmer'):
        score *= 0.6
        negatives.append("token farmer")

    if token.get('derived_has_mint_authority'):
        score *= 0.3
        negatives.append("HAS MINT AUTHORITY")
    if token.get('derived_has_freeze_authority'):
        score *= 0.5

    # CoinGecko listings (unique signals)
    if token.get('cg_is_listed'):
        score *= 1.08
        positives.append("CoinGecko listed")
    if token.get('cg_listed_on_binance'):
        score *= 1.10
        positives.append("BINANCE")
    elif token.get('cg_listed_on_coinbase'):
        score *= 1.08
        positives.append("COINBASE")

    # Surf trending
    trending_rank = token.get('surf_trending_rank')
    if trending_rank is not None and trending_rank <= 5:
        score *= 1.15
        positives.append(f"TRENDING #{trending_rank}")

    # Volume penalties
    buys_h1 = (dex.get('txns_h1', {}) or {}).get('buys', 0) or 0
    sells_h1 = (dex.get('txns_h1', {}) or {}).get('sells', 0) or 0
    if sells_h1 > 0 and buys_h1 == 0:
        score *= 0.1
        negatives.append("ONLY SELLS")
    elif sells_h1 > 0:
        sell_ratio = sells_h1 / (buys_h1 + sells_h1)
        if sell_ratio > SELL_RATIO_THRESHOLD:
            score *= 0.3
            negatives.append(f"HEAVY SELLS ({sell_ratio:.0%})")

    if vol_h24 > 0 and vol_h1 > 0:
        if vol_h1 < vol_h24 * STAGNANT_VOLUME_RATIO:
            score *= 0.5
            negatives.append("stagnant volume")

    buys_h6 = (dex.get('txns_h6', {}) or {}).get('buys', 0) or 0
    sells_h6 = (dex.get('txns_h6', {}) or {}).get('sells', 0) or 0
    total_h6 = buys_h6 + sells_h6
    if total_h6 == 0 and age_hours and age_hours > 1:
        score *= 0.4
        negatives.append("no txns in 6h")

    # RugCheck
    rc_score = token.get('rugcheck_score', 0)
    if rc_score > 10: score *= 0.2
    elif rc_score > 5: score *= 0.5

    return round(score, 2), positives, negatives

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

def get_candidates() -> List[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT chain, contract_address, channel_count, channels_seen,
               mentions, first_seen_at, last_seen_at
        FROM telegram_contracts_unique
        WHERE channel_count >= ?
        ORDER BY channel_count DESC, last_seen_at DESC
        LIMIT ?
    """, (MIN_CHANNEL_COUNT, MAX_ENRICH))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    log.info(f"Loaded {len(rows)} candidates (min {MIN_CHANNEL_COUNT} channels)")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run_enricher():
    status = EnricherResult()

    log.info("=" * 60)
    log.info("Token Enricher starting")
    log.info(f"DB: {DB_PATH}")
    log.info(f"Min channels: {MIN_CHANNEL_COUNT}")
    log.info(f"Max enrich: {MAX_ENRICH}")
    log.info(f"Top N: {TOP_N}")
    log.info("=" * 60)

    # Get candidates
    candidates = get_candidates()
    if not candidates:
        log.warning("No candidates found")
        return {'status': 'empty', 'candidates': 0}

    enriched = candidates

    # Layer 0: Dexscreener (REQUIRED)
    log.info("Layer 0: Dexscreener (market data)...")
    start = time.time()
    try:
        dex = DexscreenerEnricher()
        enriched, count = dex.enrich_batch(enriched)
        elapsed = time.time() - start
        if not enriched:
            log.error("Dexscreener returned 0 results - cannot continue")
            return {'status': 'no_enrichment', 'candidates': len(candidates)}
        status.record('Dexscreener', True, count, len(candidates), elapsed=elapsed)
    except Exception as e:
        status.record('Dexscreener', False, 0, len(candidates), str(e), time.time() - start)
        log.error(f"Dexscreener FAILED - pipeline cannot continue: {e}")
        return {'status': 'dexscreener_failed', 'error': str(e)}

    # ── Optional enrichers (try/bypass) ──

    # Layer 1: Surf
    log.info("Layer 1: Surf (market context + social)...")
    start = time.time()
    try:
        surf = SurfEnricher()
        _, count = surf.enrich_batch(enriched)
        status.record('Surf', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('Surf', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 2: GoPlus
    log.info("Layer 2: GoPlus (EVM security)...")
    start = time.time()
    try:
        gp = GoPlusEnricher()
        _, count = gp.enrich_batch(enriched)
        status.record('GoPlus', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('GoPlus', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 3: RugCheck
    log.info("Layer 3: RugCheck (Solana security)...")
    start = time.time()
    try:
        rc = RugCheckEnricher()
        _, count = rc.enrich_batch(enriched)
        status.record('RugCheck', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('RugCheck', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 4: Etherscan
    log.info("Layer 4: Etherscan (verification)...")
    start = time.time()
    try:
        es = EtherscanEnricher()
        _, count = es.enrich_batch(enriched)
        status.record('Etherscan', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('Etherscan', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 5: De.Fi
    log.info("Layer 5: De.Fi (security)...")
    start = time.time()
    try:
        di = DefiEnricher()
        _, count = di.enrich_batch(enriched)
        status.record('De.Fi', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('De.Fi', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 6: Derived (no API, always works)
    log.info("Layer 6: Derived (computed signals)...")
    start = time.time()
    try:
        der = DerivedSecurityAnalyzer()
        _, count = der.analyze_batch(enriched)
        status.record('Derived', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('Derived', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 7: CoinGecko
    log.info("Layer 7: CoinGecko (market data)...")
    start = time.time()
    try:
        cg = CoinGeckoEnricher()
        _, count = cg.enrich_batch(enriched)
        status.record('CoinGecko', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('CoinGecko', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 8: GMGN
    log.info("Layer 8: GMGN (smart money)...")
    start = time.time()
    try:
        gm = GMGNEnricher()
        _, count = gm.enrich_batch(enriched)
        status.record('GMGN', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('GMGN', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 9: Social (no API, always works)
    log.info("Layer 9: Social (Telegram DB)...")
    start = time.time()
    try:
        social = SocialSignalEnricher()
        count = 0
        for token in enriched:
            signals = social.enrich_from_enriched(token)
            token.update(signals)
            if signals:
                count += 1
        status.record('Social', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('Social', False, 0, len(enriched), str(e), time.time() - start)


    # Layer 10: Zerion — REMOVED (not tracking Solana meme tokens)
    # ── Score ──
    scored = []
    for token in enriched:
        s, pos, neg = score_token(token)
        dex = token.get('dex', {})
        scored.append({
            'contract_address': token['contract_address'],
            'chain': token['chain'],
            'symbol': dex.get('symbol', '?'),
            'name': dex.get('name', '?'),
            'score': s,
            'channel_count': token.get('channel_count', 0),
            'mentions': token.get('mentions', 0),
            'fdv': dex.get('fdv'),
            'volume_h24': dex.get('volume_h24'),
            'volume_h1': dex.get('volume_h1'),
            'age_hours': dex.get('age_hours'),
            'price_change_h1': dex.get('price_change_h1'),
            'price_change_h6': dex.get('price_change_h6'),
            'social_score': token.get('social_score'),
            'gmgn_smart_wallets': token.get('gmgn_smart_wallets'),
            'gmgn_dev_hold': token.get('gmgn_dev_hold'),
            'positives': pos,
            'negatives': neg,
            'dex_url': f"https://dexscreener.com/{token['chain']}/{token['contract_address']}",
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    top = scored[:TOP_N]

    # ── Write output ──
    output = {
        'generated_at': time.time(),
        'generated_at_iso': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
        'total_candidates': len(candidates),
        'enriched': len(enriched),
        'top_n': len(top),
        'pipeline_status': status.layers,
        'tokens': top,
    }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    # Save as Phase 1 (initial enrichment scores)
    phase1_path = Path.home() / '.hermes' / 'data' / 'token_screener' / 'top100_phase1_initial.json'
    with open(phase1_path, 'w') as f:
        json.dump({**output, 'phase': 'phase1_initial'}, f, indent=2, default=str)

    # ── Summary ──
    log.info("")
    log.info("=" * 60)
    log.info("PIPELINE STATUS:")
    log.info("=" * 60)
    for line in status.summary():
        log.info(line)

    log.info("")
    log.info("=" * 60)
    log.info("TOP 10 TOKENS:")
    log.info("=" * 60)
    for i, t in enumerate(top[:10], 1):
        fdv_val = t.get('fdv') or 0
        vol_val = t.get('volume_h24') or 0
        neg = ' | ' + ', '.join(t['negatives'][:2]) if t['negatives'] else ''
        log.info(f"  #{i} [{t['score']:6.1f}] {t['symbol']:10} {t['chain']}:{t['contract_address'][:20]}... "
                 f"ch={t['channel_count']} FDV=${fdv_val:,.0f} vol24=${vol_val:,.0f}{neg}")

    return {
        'status': 'ok',
        'total_candidates': len(candidates),
        'enriched': len(enriched),
        'top_n': len(top),
        'output_path': str(OUTPUT_PATH),
        'pipeline': {k: v['ok'] for k, v in status.layers.items()},
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Token enrichment pipeline')
    parser.add_argument('--max-tokens', type=int, default=None, help='Max tokens to enrich')
    parser.add_argument('--min-channels', type=int, default=None, help='Min channel count')
    parser.add_argument('--async-mode', action='store_true', dest='async_mode',
                        help='Run enrichment layers in parallel (async)')
    parser.add_argument('--sequential', action='store_true',
                        help='Force sequential enrichment (original behavior)')
    args = parser.parse_args()

    global MAX_ENRICH, MIN_CHANNEL_COUNT
    if args.max_tokens:
        MAX_ENRICH = args.max_tokens
    if args.min_channels:
        MIN_CHANNEL_COUNT = args.min_channels

    start = time.time()

    if args.async_mode and not args.sequential:
        # Async parallel enrichment
        from hermes_screener.async_enrichment import run_async_enrichment_sync
        candidates = get_candidates()
        if not candidates:
            log.warning("No candidates found")
            return 1
        enriched, layer_results = run_async_enrichment_sync(candidates, MAX_ENRICH)
        if enriched:
            scored = score_and_output(enriched)
            elapsed = time.time() - start
            log.info(f"\nAsync completed in {elapsed:.1f}s: {len(enriched)} tokens enriched, "
                     f"{len(scored)} scored")
            result = {'status': 'ok', 'tokens': len(enriched), 'scored': len(scored)}
        else:
            result = {'status': 'no_enrichment'}
    else:
        # Sequential enrichment (original)
        result = run_enricher()

    elapsed = time.time() - start
    log.info(f"\nCompleted in {elapsed:.1f}s: {json.dumps(result, default=str)}")
    return 0 if result.get('status') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
