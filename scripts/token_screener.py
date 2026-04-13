#!/usr/bin/env python3
"""
Token Scorer - Filter and rank tokens from the contract database.

Scoring criteria (positive):
  1. Cross-channel calls (more channels = better)         [0-25 pts]
  2. Freshness - newer is better                           [0-15 pts]
  3. Low FDV / market cap                                  [0-15 pts]
  4. Volume - high and accelerating                        [0-20 pts]
  5. Transaction activity + buy-heavy ratio                [0-15 pts]
  6. Price momentum                                        [0-10 pts]
  7. GoPlus security score (clean contract = bonus)        [bonus]

Scoring criteria (negative / disqualifiers):
  - Honeypot detected (GoPlus)                             [instant 0]
  - Heavy sells (sell ratio > 70% in h1)
  - Dev dump detected (only sells in h1)
  - High buy/sell tax (>10%)
  - Mintable contract
  - Stagnant volume (h1 volume < 1% of h24)
  - Extreme top-holder concentration (top 10 > 70%)
  - Zero recent activity (no txns in h6)

Output: top 100 tokens with scores, written to JSON.
"""

import os
import sys
import json
import time
import sqlite3
import logging
import math
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add scripts dir to path for local imports
sys.path.insert(0, str(Path(__file__).parent))
from goplus_enricher import GoPlusEnricher
from defi_enricher import DefiEnricher
from derived_security import DerivedSecurityAnalyzer
from coingecko_enricher import CoinGeckoEnricher
from social_enricher import SocialSignalEnricher
from etherscan_enricher import EtherscanEnricher
from gmgn_enricher_v2 import GMGNEnricher
from surf_enricher import SurfEnricher
from rugcheck_enricher import RugCheckEnricher

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = Path.home() / '.hermes' / 'data' / 'central_contracts.db'
OUTPUT_PATH = Path.home() / '.hermes' / 'data' / 'token_screener' / 'top100.json'
LOG_FILE = Path.home() / '.hermes' / 'logs' / 'token_screener.log'

DEXSCREENER_BASE = 'https://api.dexscreener.com/latest/dex'
DEXSCREENER_DELAY = float(os.getenv('DEXSCREENER_RATE_LIMIT_DELAY', '1.0'))
TOP_N = int(os.getenv('SCREENER_TOP_N', '100'))
MAX_ENRICH = int(os.getenv('SCREENER_MAX_ENRICH', '300'))
MIN_CHANNEL_COUNT = int(os.getenv('SCREENER_MIN_CHANNELS', '2'))

# Scoring weights
W_CHANNEL = 25.0
W_FRESHNESS = 15.0
W_LOW_FDV = 15.0
W_VOLUME = 20.0
W_TXNS = 15.0
W_MOMENTUM = 10.0

# Disqualifier thresholds
SELL_RATIO_THRESHOLD = 0.70      # >70% sells in h1
STAGNANT_VOLUME_RATIO = 0.01     # h1 < 1% of h24 volume
NO_ACTIVITY_HOURS = 6            # no txns in h6 = dead
MAX_TOP_HOLDER_CONCENTRATION = 0.80  # top 3 holders > 80%

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('token_screener')

# ── Database ────────────────────────────────────────────────────────────────
def get_candidates() -> List[dict]:
    """Get tokens from DB that have cross-channel mentions."""
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

# ── Dexscreener Enrichment ──────────────────────────────────────────────────
class DexscreenerEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.last_request = 0

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < DEXSCREENER_DELAY:
            time.sleep(DEXSCREENER_DELAY - elapsed)
        self.last_request = time.time()

    def enrich(self, token_address: str) -> dict:
        """Enrich a single token with Dexscreener data."""
        self._rate_limit()
        try:
            resp = self.session.get(
                f'{DEXSCREENER_BASE}/tokens/{token_address}',
                timeout=10
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
        except Exception as e:
            log.debug(f"Dexscreener fail for {token_address[:12]}: {e}")
            return {}

        pairs = data.get('pairs', [])
        if not pairs:
            return {}

        # Best pair by liquidity
        best = max(pairs, key=lambda p: p.get('liquidity', {}).get('usd', 0) or 0)

        txns = best.get('txns', {})
        volume = best.get('volume', {})
        price_change = best.get('priceChange', {})

        return {
            'fdv': best.get('fdv'),
            'market_cap': best.get('marketCap'),
            'liquidity_usd': best.get('liquidity', {}).get('usd'),
            'volume_m5': volume.get('m5', 0) or 0,
            'volume_h1': volume.get('h1', 0) or 0,
            'volume_h6': volume.get('h6', 0) or 0,
            'volume_h24': volume.get('h24', 0) or 0,
            'txns_m5': txns.get('m5', {}),
            'txns_h1': txns.get('h1', {}),
            'txns_h6': txns.get('h6', {}),
            'txns_h24': txns.get('h24', {}),
            'price_change_m5': price_change.get('m5'),
            'price_change_h1': price_change.get('h1'),
            'price_change_h6': price_change.get('h6'),
            'price_change_h24': price_change.get('h24'),
            'age_hours': self._age_hours(best.get('pairCreatedAt')),
            'dex': best.get('dexId'),
            'symbol': best.get('baseToken', {}).get('symbol'),
            'name': best.get('baseToken', {}).get('name'),
            'pair_address': best.get('pairAddress'),
        }

    def _age_hours(self, created_at_ms) -> Optional[float]:
        if not created_at_ms:
            return None
        return round((time.time() * 1000 - created_at_ms) / 3600000, 2)

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        """Enrich a batch of token candidates."""
        results = []
        for i, token in enumerate(tokens):
            addr = token['contract_address']
            if (i + 1) % 50 == 0:
                log.info(f"  Enriching {i+1}/{len(tokens)}...")
            dex_data = self.enrich(addr)
            if dex_data:
                merged = {**token, 'dex': dex_data}
                results.append(merged)
        log.info(f"Enriched {len(results)}/{len(tokens)} tokens (Dexscreener returned data)")
        return results

# ── Scoring ─────────────────────────────────────────────────────────────────
def score_token(token: dict) -> Tuple[float, List[str], List[str]]:
    """
    Score a single token. Returns (score, positive_signals, negative_signals).
    Score is 0-100 positive minus penalties.
    """
    dex = token.get('dex', {})
    score = 0.0
    positives = []
    negatives = []

    # ── 1. Cross-channel calls + social momentum (0-35) ──
    social_score = token.get('social_score', 0)
    channel_count = token.get('channel_count', 0)

    # Use social_score if available (it includes channel_count + velocity + recency)
    if social_score:
        # social_score is 0-100, scale to 0-35
        social_scaled = social_score * 0.35
        score += social_scaled
        if token.get('social_hot'):
            positives.append(f"social HOT (ch={channel_count} mentions/hr={token.get('social_mentions_per_hour', 0)})")
        elif channel_count >= 5:
            positives.append(f"called in {channel_count} channels")
    else:
        # Fallback to raw channel count
        import math
        channel_score = min(25, 5 + (math.log2(max(1, channel_count)) * 7))
        score += channel_score
        if channel_count >= 5:
            positives.append(f"called in {channel_count} channels")

    # ── 2. Freshness (0-15) ──
    age_hours = dex.get('age_hours')
    if age_hours is not None:
        # Newer = better. <6h = 15pts, <24h = 12, <72h = 8, <168h = 4, else 1
        if age_hours < 6:
            freshness = 15
        elif age_hours < 24:
            freshness = 12
        elif age_hours < 72:
            freshness = 8
        elif age_hours < 168:
            freshness = 4
        else:
            freshness = 1
        score += freshness
        positives.append(f"age {age_hours:.1f}h")

    # ── 3. Low FDV (0-15) ──
    fdv = dex.get('fdv') or dex.get('market_cap')
    if fdv and fdv > 0:
        # Lower = better. <50K = 15, <200K = 12, <1M = 9, <5M = 6, <50M = 3
        if fdv < 50_000:
            fdv_score = 15
        elif fdv < 200_000:
            fdv_score = 12
        elif fdv < 1_000_000:
            fdv_score = 9
        elif fdv < 5_000_000:
            fdv_score = 6
        elif fdv < 50_000_000:
            fdv_score = 3
        else:
            fdv_score = 1
        score += fdv_score
        positives.append(f"FDV ${fdv:,.0f}")

    # ── 4. Volume (0-20) ──
    vol_h24 = dex.get('volume_h24', 0) or 0
    vol_h1 = dex.get('volume_h1', 0) or 0
    vol_m5 = dex.get('volume_m5', 0) or 0

    if vol_h24 > 0:
        # Absolute volume scoring
        if vol_h24 > 500_000:
            vol_abs = 10
        elif vol_h24 > 100_000:
            vol_abs = 8
        elif vol_h24 > 25_000:
            vol_abs = 6
        elif vol_h24 > 5_000:
            vol_abs = 4
        elif vol_h24 > 1_000:
            vol_abs = 2
        else:
            vol_abs = 1

        # Volume acceleration: h1 is hot relative to h24 average
        vol_h1_ratio = (vol_h1 * 24) / vol_h24 if vol_h24 > 0 else 0
        if vol_h1_ratio > 3:
            vol_accel = 10  # Very hot
        elif vol_h1_ratio > 1.5:
            vol_accel = 7
        elif vol_h1_ratio > 0.5:
            vol_accel = 4
        elif vol_m5 > 0:
            vol_accel = 2
        else:
            vol_accel = 0

        score += vol_abs + vol_accel
        positives.append(f"vol24 ${vol_h24:,.0f}")
    else:
        negatives.append("no volume data")

    # ── 5. Transaction activity + buy ratio (0-15) ──
    txns_h1 = dex.get('txns_h1', {})
    txns_h6 = dex.get('txns_h6', {})
    txns_h24 = dex.get('txns_h24', {})

    buys_h1 = txns_h1.get('buys', 0) or 0
    sells_h1 = txns_h1.get('sells', 0) or 0
    buys_h6 = txns_h6.get('buys', 0) or 0
    sells_h6 = txns_h6.get('sells', 0) or 0
    buys_h24 = txns_h24.get('buys', 0) or 0
    sells_h24 = txns_h24.get('sells', 0) or 0
    total_h24 = buys_h24 + sells_h24

    if total_h24 > 0:
        # Transaction count scoring
        if total_h24 > 500:
            txn_count_score = 7
        elif total_h24 > 100:
            txn_count_score = 5
        elif total_h24 > 30:
            txn_count_score = 3
        else:
            txn_count_score = 1

        # Buy ratio scoring
        buy_ratio = buys_h24 / total_h24 if total_h24 > 0 else 0.5
        if buy_ratio > 0.7:
            buy_score = 8
        elif buy_ratio > 0.6:
            buy_score = 6
        elif buy_ratio > 0.5:
            buy_score = 4
        elif buy_ratio > 0.4:
            buy_score = 2
        else:
            buy_score = 0

        score += txn_count_score + buy_score
        positives.append(f"txns {total_h24} (buy {buy_ratio:.0%})")

    # ── 6. Price momentum (0-10) ──
    pc_m5 = dex.get('price_change_m5')
    pc_h1 = dex.get('price_change_h1')
    pc_h6 = dex.get('price_change_h6')
    pc_h24 = dex.get('price_change_h24')

    momentum = 0
    if pc_h1 is not None and pc_h1 > 0:
        momentum += 3
    if pc_h6 is not None and pc_h6 > 0:
        momentum += 3
    if pc_h24 is not None and pc_h24 > 10:
        momentum += 4
    elif pc_h24 is not None and pc_h24 > 0:
        momentum += 2
    score += momentum
    if pc_h1 is not None:
        positives.append(f"price h1 {pc_h1:+.1f}%")

    # ── Negative signals (penalties and disqualifiers) ──

    # Etherscan: verified contract (STRONG positive signal)
    if token.get('etherscan_verified'):
        score *= 1.20  # +20% for verified source code
        positives.append(f"VERIFIED contract ({token.get('etherscan_contract_name', '')})")
    elif token.get('etherscan_contract_name') == '' and token.get('etherscan_is_verified') is False:
        # Explicitly unverified EVM contract
        score *= 0.90
        negatives.append("unverified contract")

    # Etherscan: proxy contract (informational)
    if token.get('etherscan_is_proxy'):
        score *= 1.03  # slight bonus - proxy = more established pattern

    # ── RugCheck Signals (Solana security) ──

    # RugCheck: RUGGED (instant disqualifier)
    if token.get('rugcheck_rugged'):
        score = 0
        negatives.append("RUGGED (RugCheck)")
        return round(score, 2), positives, negatives

    # RugCheck: high risk score (>5 = suspicious)
    rc_score = token.get('rugcheck_score', 0)
    if rc_score > 10:
        score *= 0.2
        negatives.append(f"rug score {rc_score} (RugCheck)")
    elif rc_score > 5:
        score *= 0.5
        negatives.append(f"rug score {rc_score} (RugCheck)")
    elif rc_score > 3:
        score *= 0.7
        negatives.append(f"rug score {rc_score}")

    # RugCheck: risk flags
    rc_risks = token.get('rugcheck_risk_count', 0)
    if rc_risks > 3:
        score *= 0.3
        negatives.append(f"{rc_risks} risk flags (RugCheck)")
    elif rc_risks > 0:
        score *= max(0.5, 1 - rc_risks * 0.15)
        risks = token.get('rugcheck_risks', [])
        negatives.append(f"RugCheck: {', '.join(risks[:3])}")

    # RugCheck: mint/freeze authority
    if token.get('rugcheck_mint_renounced') is False:
        score *= 0.3
        negatives.append("mint not renounced (RugCheck)")
    if token.get('rugcheck_freeze_renounced') is False:
        score *= 0.5
        negatives.append("freeze not renounced (RugCheck)")

    # RugCheck: mutable metadata
    if token.get('rugcheck_mutable'):
        score *= 0.85
        negatives.append("mutable metadata")

    # RugCheck: insider detection
    insiders = token.get('rugcheck_insiders_detected', 0)
    if insiders > 20:
        score *= 0.4
        negatives.append(f"{insiders} insiders detected (RugCheck)")
    elif insiders > 5:
        score *= 0.7
        negatives.append(f"{insiders} insiders detected")

    # RugCheck: transfer fee
    if token.get('rugcheck_has_transfer_fee'):
        fee = token.get('rugcheck_transfer_fee_pct', 0)
        score *= max(0.3, 1 - fee / 100)
        negatives.append(f"{fee}% transfer fee")

    # RugCheck: top holder concentration
    rc_top10 = token.get('rugcheck_top_10_holder_pct')
    if rc_top10 is not None and rc_top10 > 80:
        score *= 0.3
        negatives.append(f"top 10 hold {rc_top10:.0f}% (RugCheck)")
    elif rc_top10 is not None and rc_top10 > 60:
        score *= 0.6

    # RugCheck: max single holder
    rc_max = token.get('rugcheck_max_holder_pct')
    if rc_max is not None and rc_max > 30:
        score *= 0.4
        negatives.append(f"max holder {rc_max:.0f}%")

    # RugCheck: insider holders in top 20
    insider_holders = token.get('rugcheck_insider_holders', 0)
    if insider_holders > 3:
        score *= 0.6
        negatives.append(f"{insider_holders} insider holders in top 20")

    # RugCheck: safe token bonus
    if rc_score <= 1 and rc_risks == 0 and not token.get('rugcheck_rugged'):
        score *= 1.05
        if insiders == 0:
            score *= 1.03
            positives.append("RugCheck verified safe")

    # ── GMGN Signals (dev conviction, bot detection, smart money) ──

    # GMGN: HONEYPOT (instant disqualifier)
    if token.get('gmgn_honeypot'):
        score = 0
        negatives.append("HONEYPOT (GMGN)")
        return round(score, 2), positives, negatives

    # GMGN: Dev conviction - creator still holding (STRONG positive)
    if token.get('gmgn_dev_hold'):
        score *= 1.25
        positives.append("DEV STILL HOLDING (GMGN)")
    elif token.get('gmgn_creator_status') == 'creator_sold':
        score *= 0.5
        negatives.append("dev dumped (GMGN)")

    # GMGN: Dev team hold rate
    dev_rate = token.get('gmgn_dev_team_hold_rate')
    if dev_rate is not None:
        if dev_rate > 0.05:
            score *= 1.10
            positives.append(f"team holds {dev_rate:.0%}")
        elif dev_rate == 0:
            score *= 0.8
            negatives.append("team holds 0%")

    # GMGN: Renounced mint authority
    if token.get('gmgn_renounced_mint'):
        score *= 1.10
        positives.append("mint renounced (GMGN)")
    elif token.get('gmgn_renounced_mint') is False:
        score *= 0.3
        negatives.append("MINT NOT RENOUNCED (GMGN)")

    # GMGN: Renounced freeze authority
    if token.get('gmgn_renounced_freeze'):
        score *= 1.05
    elif token.get('gmgn_renounced_freeze') is False:
        score *= 0.5
        negatives.append("freeze not renounced (GMGN)")

    # GMGN: LP burned
    burn = token.get('gmgn_burn_status')
    if burn == 'burn':
        score *= 1.15
        positives.append("LP BURNED (GMGN)")
    elif burn == 'none':
        score *= 0.7
        negatives.append("LP not burned")

    # GMGN: Bot degen rate (high = bad)
    bot_rate = token.get('gmgn_bot_degen_rate')
    if bot_rate is not None and bot_rate > 0.3:
        score *= max(0.3, 1 - bot_rate)
        negatives.append(f"{bot_rate:.0%} bot wallets (GMGN)")

    # GMGN: Entrapment traders (scam indicator)
    entrap = token.get('gmgn_top_entrapment')
    if entrap is not None and entrap > 0.15:
        score *= 0.5
        negatives.append(f"{entrap:.0%} entrapment traders")

    # GMGN: Smart money presence (positive)
    smart = token.get('gmgn_smart_wallets', 0)
    if smart > 20:
        score *= 1.15
        positives.append(f"{smart} smart wallets (GMGN)")
    elif smart > 5:
        score *= 1.08
        positives.append(f"{smart} smart wallets")

    # GMGN: Renowned wallets (KOL signal)
    renowned = token.get('gmgn_renowned_wallets', 0)
    if renowned > 3:
        score *= 1.10
        positives.append(f"{renowned} renowned wallets")

    # GMGN: Sniper wallets (moderate risk)
    snipers = token.get('gmgn_sniper_wallets', 0)
    if snipers > 50:
        score *= 0.7
        negatives.append(f"{snipers} sniper wallets")

    # GMGN: Rat traders (scam indicator)
    rats = token.get('gmgn_rat_traders', 0)
    if rats > 10:
        score *= 0.6
        negatives.append(f"{rats} rat traders (GMGN)")

    # GMGN: Top holder concentration
    gmgn_top10 = token.get('gmgn_top_10_holder_rate')
    if gmgn_top10 is not None:
        if gmgn_top10 > 0.5:
            score *= 0.4
            negatives.append(f"top 10 hold {gmgn_top10:.0%} (GMGN)")
        elif gmgn_top10 > 0.3:
            score *= 0.7
            negatives.append(f"top 10 hold {gmgn_top10:.0%}")

    # GMGN: Dev is token farmer (created many tokens before)
    if token.get('gmgn_dev_token_farmer'):
        score *= 0.6
        count = token.get('gmgn_dev_token_count', 0)
        negatives.append(f"dev created {count} tokens (farmer)")

    # GMGN: Holder count bonus
    holders = token.get('gmgn_holder_count')
    if holders and holders > 10000:
        score *= 1.05
    elif holders and holders > 5000:
        score *= 1.03

    # GMGN: CTO flag (community takeover = positive)
    if token.get('gmgn_cto_flag'):
        score *= 1.10
        positives.append("community takeover (CTO)")

    # GMGN: Social presence
    if token.get('gmgn_has_twitter'):
        score *= 1.03
    if token.get('gmgn_has_website'):
        score *= 1.02

    # GoPlus honeypot detection (instant disqualifier)
    if token.get('goplus_is_honeypot'):
        score = 0
        negatives.append("HONEYPOT DETECTED (GoPlus)")
        return round(score, 2), positives, negatives

    # GoPlus: cannot buy or cannot sell all
    if token.get('goplus_cannot_buy'):
        score *= 0.1
        negatives.append("CANNOT BUY (GoPlus)")
    if token.get('goplus_cannot_sell_all'):
        score *= 0.3
        negatives.append("CANNOT SELL ALL (GoPlus)")

    # GoPlus: high buy/sell tax (>10%)
    buy_tax = token.get('goplus_buy_tax')
    sell_tax = token.get('goplus_sell_tax')
    if buy_tax is not None and buy_tax > 0.10:
        score *= max(0.2, 1 - buy_tax)
        negatives.append(f"high buy tax ({buy_tax:.0%})")
    if sell_tax is not None and sell_tax > 0.10:
        score *= max(0.2, 1 - sell_tax)
        negatives.append(f"high sell tax ({sell_tax:.0%})")

    # GoPlus: mintable contract
    if token.get('goplus_is_mintable'):
        score *= 0.5
        negatives.append("MINTABLE (GoPlus)")

    # GoPlus: owner can change balance
    if token.get('goplus_owner_can_change_balance'):
        score *= 0.2
        negatives.append("OWNER CAN CHANGE BALANCE (GoPlus)")

    # GoPlus: can take back ownership
    if token.get('goplus_can_take_back_ownership'):
        score *= 0.3
        negatives.append("CAN TAKE BACK OWNERSHIP (GoPlus)")

    # GoPlus: transfer pausable
    if token.get('goplus_transfer_pausable'):
        score *= 0.5
        negatives.append("TRANSFER PAUSABLE (GoPlus)")

    # GoPlus: slippage modifiable
    if token.get('goplus_slippage_modifiable'):
        score *= 0.7
        negatives.append("SLIPPAGE MODIFIABLE (GoPlus)")

    # GoPlus: top holder concentration (>70% in top 10)
    top_10_pct = token.get('goplus_top_10_holder_pct')
    if top_10_pct is not None and top_10_pct > 70:
        penalty = 0.3 if top_10_pct > 85 else 0.5
        score *= penalty
        negatives.append(f"top 10 holders {top_10_pct:.0f}%")

    # GoPlus: honeypot by same creator
    if token.get('goplus_honeypot_same_creator'):
        score *= 0.1
        negatives.append("CREATOR HAS OTHER HONEYPOTS (GoPlus)")

    # GoPlus bonus: clean contract with trust list
    if token.get('goplus_is_trust_list'):
        score *= 1.15
        positives.append("GoPlus trust list")
    elif any(k.startswith('goplus_') for k in token) and not negatives:
        # Has GoPlus data and no flags = clean contract bonus
        score *= 1.10
        positives.append("GoPlus verified clean")

    # GoPlus: CEX listed bonus
    if token.get('goplus_is_in_cex'):
        score *= 1.05
        positives.append("CEX listed")

    # ── De.Fi Security Signals ──

    # De.Fi: scammed flag (instant disqualifier)
    if token.get('defi_scammed'):
        score = 0
        negatives.append("SCAMMED (De.Fi)")
        return round(score, 2), positives, negatives

    # De.Fi: critical issues
    critical = token.get('defi_issues_critical', 0) or 0
    if critical > 0:
        score *= max(0.1, 0.5 ** critical)
        negatives.append(f"{critical} critical issues (De.Fi)")

    # De.Fi: high severity issues
    high = token.get('defi_issues_high', 0) or 0
    if high > 0:
        score *= max(0.3, 0.8 ** high)
        negatives.append(f"{high} high issues (De.Fi)")

    # De.Fi: core issues (Pausable, Proxy, etc)
    core_issues = token.get('defi_core_issues', [])
    dangerous_core = [i for i in core_issues if i in ('Pausable', 'Proxy Upgradeability', 'Mintable', 'Owner Can Change Balance')]
    if dangerous_core:
        score *= 0.8
        negatives.append(f"De.Fi flags: {', '.join(dangerous_core)}")

    # De.Fi: top holder concentration
    defi_top_pct = token.get('defi_top_10_holder_pct')
    if defi_top_pct is not None and defi_top_pct > 70:
        penalty = 0.3 if defi_top_pct > 85 else 0.5
        score *= penalty
        negatives.append(f"De.Fi: top 10 hold {defi_top_pct:.0f}%")

    # De.Fi: whitelisted bonus
    if token.get('defi_whitelisted'):
        score *= 1.10
        positives.append("De.Fi whitelisted")

    # ── Derived Security Signals (for tokens without GoPlus/De.Fi) ──

    # Derived: mint authority on Solana (critical risk)
    if token.get('derived_has_mint_authority'):
        score *= 0.3
        negatives.append("HAS MINT AUTHORITY (can print more tokens)")
    if token.get('derived_has_freeze_authority'):
        score *= 0.5
        negatives.append("HAS FREEZE AUTHORITY")

    # Derived: whale dominant (>50% single holder)
    max_pct = token.get('derived_max_holder_pct')
    if max_pct is not None and max_pct > 50:
        score *= 0.2
        negatives.append(f"whale holds {max_pct:.0f}%")
    elif max_pct is not None and max_pct > 25:
        score *= 0.5
        negatives.append(f"top holder {max_pct:.0f}%")

    # Derived: top holder concentration
    top_10 = token.get('derived_top_10_holder_pct')
    if top_10 is not None and top_10 > 80:
        score *= 0.3
        negatives.append(f"top 10 hold {top_10:.0f}%")
    elif top_10 is not None and top_10 > 60:
        score *= 0.6
        negatives.append(f"top 10 hold {top_10:.0f}%")

    # Derived: volume dying
    if token.get('derived_volume_dying'):
        score *= 0.4
        negatives.append("volume decaying (h6 << h24)")

    # Derived: no recent activity
    if token.get('derived_no_recent_activity'):
        score *= 0.3
        negatives.append("zero activity in h1")

    # Derived: massive dump
    if token.get('derived_massive_dump'):
        score *= 0.2
        negatives.append("MASSIVE DUMP (h1 > -50%)")

    # Derived: possible rug
    if token.get('derived_possible_rug'):
        score *= 0.1
        negatives.append("POSSIBLE RUG (dump + volume)")

    # Derived: pump and dump pattern
    if token.get('derived_pump_and_dump'):
        score *= 0.3
        negatives.append("pump & dump pattern")

    # Derived: liquidity risk
    liq_risk = token.get('derived_liq_risk')
    if liq_risk == 'critical':
        score *= 0.4
        negatives.append("critical liquidity")
    elif liq_risk == 'high':
        score *= 0.7
        negatives.append("low liquidity")

    # Derived: suspicious buy inflation
    if token.get('derived_suspect_buy_inflate'):
        score *= 0.7
        negatives.append("buy ratio >85% (possible wash)")

    # Derived: brand new (<30min)
    if token.get('derived_brand_new'):
        score *= 0.6
        negatives.append("brand new (<30min)")

    # Derived: buy ratio declining
    if token.get('derived_buy_ratio_declining'):
        score *= 0.8
        negatives.append("buy ratio declining")

    # Derived: activity hot bonus
    if token.get('derived_activity_hot'):
        score *= 1.05
        positives.append("activity spiking")

    # Derived: volume accelerating bonus
    if token.get('derived_volume_accelerating'):
        score *= 1.05
        positives.append("volume accelerating")

    # ── CoinGecko Market Signals ──

    # CoinGecko: listed on CoinGecko = legitimacy bonus
    if token.get('cg_is_listed'):
        score *= 1.08
        positives.append("CoinGecko listed")

    # CoinGecko: sentiment ratio
    cg_up = token.get('cg_sentiment_up_pct')
    cg_down = token.get('cg_sentiment_down_pct')
    if cg_up is not None and cg_down is not None:
        total_votes = cg_up + cg_down
        if total_votes > 10:  # meaningful sample
            sentiment_ratio = cg_up / total_votes
            if sentiment_ratio > 0.7:
                score *= 1.05
                positives.append(f"bullish sentiment ({sentiment_ratio:.0%})")
            elif sentiment_ratio < 0.3:
                score *= 0.85
                negatives.append(f"bearish sentiment ({sentiment_ratio:.0%})")

    # CoinGecko: ATH recovery potential (how far from ATH)
    ath_change = token.get('cg_ath_change_pct')
    if ath_change is not None:
        if ath_change > -30:  # near ATH
            score *= 0.9  # less upside
        elif ath_change < -95:  # crashed hard
            score *= 0.7
            negatives.append(f"{ath_change:.0f}% from ATH")

    # CoinGecko: 24h price momentum
    cg_pc24 = token.get('cg_price_change_24h_pct')
    if cg_pc24 is not None:
        if cg_pc24 > 20:
            score *= 1.05
        elif cg_pc24 < -30:
            score *= 0.8

    # CoinGecko: meme coin flag (informational, slight penalty)
    if token.get('cg_is_meme'):
        score *= 0.95

    # CoinGecko: market cap rank (if it's a known ranked token)
    cg_mcap = token.get('cg_market_cap')
    if cg_mcap and cg_mcap > 100_000_000:  # >100M mcap
        score *= 1.05
        positives.append(f"mcap ${cg_mcap/1e6:.0f}M")

    # ── Surf Social Signals ──

    # Surf: social sentiment score (-1 to +1)
    surf_sent = token.get('surf_social_sentiment')
    if surf_sent is not None:
        if surf_sent > 0.3:
            score *= 1.10
            positives.append(f"bullish social ({surf_sent:.2f})")
        elif surf_sent > 0.1:
            score *= 1.05
        elif surf_sent < -0.2:
            score *= 0.85
            negatives.append(f"bearish social ({surf_sent:.2f})")

    # Surf: mindshare trend (increasing = growing attention)
    mindshare_change = token.get('surf_mindshare_change')
    if mindshare_change is not None:
        if mindshare_change > 0.2:
            score *= 1.10
            positives.append(f"social attention +{mindshare_change:.0%}")
        elif mindshare_change > 0:
            score *= 1.03
        elif mindshare_change < -0.3:
            score *= 0.85
            negatives.append(f"social fading ({mindshare_change:.0%})")

    # Surf: trending rank (in top 20 trending projects)
    trending_rank = token.get('surf_trending_rank')
    if trending_rank is not None:
        if trending_rank <= 5:
            score *= 1.15
            positives.append(f"TRENDING #{trending_rank}")
        elif trending_rank <= 10:
            score *= 1.10
            positives.append(f"trending #{trending_rank}")
        elif trending_rank <= 20:
            score *= 1.05

    # Surf: Fear & Greed market context
    fg = token.get('surf_fear_greed')
    if fg is not None:
        # During extreme fear, quality tokens are undervalued = opportunity
        if fg < 20:
            score *= 1.05  # slight bonus - contrarian buying
        elif fg > 80:
            score *= 0.95  # slight penalty - everything is inflated

    # CoinGecko: major exchange listings (big legitimacy signal)
    major_ex = token.get('cg_major_exchange_count', 0)
    if major_ex > 0:
        score *= 1.0 + (major_ex * 0.05)  # +5% per major exchange
        exchanges = token.get('cg_major_exchange_listings', [])
        if token.get('cg_listed_on_binance'):
            score *= 1.10
            positives.append("BINANCE listed")
        elif token.get('cg_listed_on_coinbase'):
            score *= 1.08
            positives.append("COINBASE listed")
        elif major_ex > 0:
            positives.append(f"listed on {major_ex} major exchanges")

    # Heavy sells
    if sells_h1 > 0 and buys_h1 > 0:
        sell_ratio = sells_h1 / (buys_h1 + sells_h1)
        if sell_ratio > SELL_RATIO_THRESHOLD:
            score *= 0.3  # 70% penalty
            negatives.append(f"HEAVY SELLS ({sell_ratio:.0%} in h1)")
    elif sells_h1 > 0 and buys_h1 == 0:
        score *= 0.1  # 90% penalty - only sells
        negatives.append("ONLY SELLS in h1 (possible dev dump)")

    # Stagnant volume
    if vol_h24 > 0 and vol_h1 > 0:
        if vol_h1 < vol_h24 * STAGNANT_VOLUME_RATIO:
            score *= 0.5
            negatives.append("stagnant volume (h1 < 1% of h24)")

    # No recent activity
    total_h6 = buys_h6 + sells_h6
    if total_h6 == 0 and age_hours and age_hours > 1:
        score *= 0.4
        negatives.append(f"no txns in {NO_ACTIVITY_HOURS}h")

    # Extreme holder concentration (if available - placeholder for future GMGN integration)
    # top_holder_pct = dex.get('top_holder_concentration')
    # if top_holder_pct and top_holder_pct > MAX_TOP_HOLDER_CONCENTRATION:
    #     score *= 0.5
    #     negatives.append(f"top holders hold {top_holder_pct:.0%}")

    return round(score, 2), positives, negatives


# ── Main ────────────────────────────────────────────────────────────────────
def run_screener():
    """Main scoring pipeline."""
    log.info("=" * 60)
    log.info("Token Screener starting")
    log.info(f"DB: {DB_PATH}")
    log.info(f"Min channels: {MIN_CHANNEL_COUNT}")
    log.info(f"Max enrich: {MAX_ENRICH}")
    log.info(f"Top N: {TOP_N}")
    log.info("=" * 60)

    # 1. Get candidates from DB
    candidates = get_candidates()
    if not candidates:
        log.warning("No candidates found")
        return {'status': 'empty', 'candidates': 0}

    # 2. Enrich with Dexscreener
    enricher = DexscreenerEnricher()
    enriched = enricher.enrich_batch(candidates)
    if not enriched:
        log.warning("No tokens enriched from Dexscreener")
        return {'status': 'no_enrichment', 'candidates': len(candidates)}

    # 1. Market context + per-token social (Surf)
    log.info("Getting market context + social data (Surf)...")
    surf = SurfEnricher()
    enriched = surf.enrich_batch(enriched)
    fg = enriched[0].get('surf_fear_greed') if enriched else None
    surf_social = sum(1 for t in enriched if t.get('surf_social_sentiment') is not None)
    log.info(f"Surf: Fear&Greed={fg}, {surf_social} tokens with social sentiment")

    # 2b. Enrich with GoPlus security data (EVM chains only)
    log.info("Enriching with GoPlus security data...")
    goplus = GoPlusEnricher()
    enriched = goplus.enrich_batch(enriched)
    goplus_count = sum(1 for t in enriched if any(k.startswith('goplus_') for k in t))
    log.info(f"GoPlus enriched: {goplus_count}/{len(enriched)} tokens")

    # 2b1. RugCheck security (Solana tokens)
    log.info("Enriching with RugCheck security data...")
    rugcheck = RugCheckEnricher()
    enriched = rugcheck.enrich_batch(enriched)
    rc_count = sum(1 for t in enriched if any(k.startswith('rugcheck_') for k in t))
    log.info(f"RugCheck enriched: {rc_count}/{len(enriched)} tokens")

    # 2b2. Etherscan contract verification (EVM chains)
    log.info("Checking Etherscan contract verification...")
    etherscan = EtherscanEnricher()
    enriched = etherscan.enrich_batch(enriched)
    verified_count = sum(1 for t in enriched if t.get('etherscan_verified'))
    log.info(f"Etherscan: {verified_count}/{len(enriched)} verified contracts")

    # 2c. Enrich with De.Fi security data (Ethereum/BSC/Solana/Base chains)
    log.info("Enriching with De.Fi security data...")
    defi = DefiEnricher()
    enriched = defi.enrich_batch(enriched)
    defi_count = sum(1 for t in enriched if any(k.startswith('defi_') for k in t))
    log.info(f"De.Fi enriched: {defi_count}/{len(enriched)} tokens")

    # 2d. Derived security analysis for tokens without GoPlus/De.Fi data
    log.info("Running derived security analysis...")
    derived_analyzer = DerivedSecurityAnalyzer()
    enriched = derived_analyzer.analyze_batch(enriched)
    derived_count = sum(1 for t in enriched if any(k.startswith('derived_') for k in t))
    log.info(f"Derived signals: {derived_count}/{len(enriched)} tokens")

    # 2e. CoinGecko market data (price, sentiment, categories)
    log.info("Enriching with CoinGecko market data...")
    cg = CoinGeckoEnricher()
    enriched = cg.enrich_batch(enriched)
    cg_count = sum(1 for t in enriched if t.get('cg_is_listed'))
    log.info(f"CoinGecko enriched: {cg_count}/{len(enriched)} tokens")

    # 2e2. GMGN data (dev conviction, bot detection, smart money, security)
    log.info("Enriching with GMGN data...")
    gmgn = GMGNEnricher()
    enriched = gmgn.enrich_batch(enriched)
    gmgn_count = sum(1 for t in enriched if any(k.startswith('gmgn_') for k in t))
    log.info(f"GMGN enriched: {gmgn_count}/{len(enriched)} tokens")

    # 2f. Social signals (Telegram mentions, velocity, recency + CoinGecko sentiment)
    log.info("Computing social signals...")
    social = SocialSignalEnricher()
    enriched = [dict(token, **social.enrich_from_enriched(token)) for token in enriched]
    log.info(f"Social signals computed for {len(enriched)} tokens")

    # 3. Score all tokens
    scored = []
    for token in enriched:
        score, positives, negatives = score_token(token)
        dex = token.get('dex', {})
        scored.append({
            'contract_address': token['contract_address'],
            'chain': token['chain'],
            'symbol': dex.get('symbol', '?'),
            'name': dex.get('name', '?'),
            'score': score,
            'channel_count': token.get('channel_count', 0),
            'mentions': token.get('mentions', 0),
            'fdv': dex.get('fdv'),
            'volume_h24': dex.get('volume_h24'),
            'volume_h1': dex.get('volume_h1'),
            'age_hours': dex.get('age_hours'),
            'price_change_h1': dex.get('price_change_h1'),
            'price_change_h6': dex.get('price_change_h6'),
            'buy_ratio': calc_buy_ratio(dex),
            'total_txns_h24': calc_total_txns(dex, 'h24'),
            'goplus_honeypot': token.get('goplus_is_honeypot'),
            'goplus_buy_tax': token.get('goplus_buy_tax'),
            'goplus_sell_tax': token.get('goplus_sell_tax'),
            'goplus_holder_count': token.get('goplus_holder_count'),
            'goplus_is_mintable': token.get('goplus_is_mintable'),
            'goplus_top_10_holder_pct': token.get('goplus_top_10_holder_pct'),
            'defi_project_name': token.get('defi_project_name'),
            'defi_issues_critical': token.get('defi_issues_critical'),
            'defi_issues_total': token.get('defi_issues_total'),
            'defi_scammed': token.get('defi_scammed'),
            'defi_whitelisted': token.get('defi_whitelisted'),
            'defi_top_10_holder_pct': token.get('defi_top_10_holder_pct'),
            'cg_price_usd': token.get('cg_price_usd'),
            'cg_market_cap': token.get('cg_market_cap'),
            'cg_sentiment_up_pct': token.get('cg_sentiment_up_pct'),
            'cg_is_listed': token.get('cg_is_listed'),
            'cg_is_meme': token.get('cg_is_meme'),
            'cg_ath_change_pct': token.get('cg_ath_change_pct'),
            'derived_has_mint_authority': token.get('derived_has_mint_authority'),
            'derived_max_holder_pct': token.get('derived_max_holder_pct'),
            'derived_top_10_holder_pct': token.get('derived_top_10_holder_pct'),
            'social_score': token.get('social_score'),
            'social_channel_count': token.get('social_channel_count'),
            'social_mentions_per_hour': token.get('social_mentions_per_hour'),
            'social_hot': token.get('social_hot'),
            'social_recency_hours': token.get('social_recency_hours'),
            'surf_fear_greed': token.get('surf_fear_greed'),
            'positives': positives,
            'negatives': negatives,
            'dex_url': f"https://dexscreener.com/{token['chain']}/{token['contract_address']}",
            'first_seen': token.get('first_seen_at'),
            'last_seen': token.get('last_seen_at'),
        })

    # 4. Sort by score descending
    scored.sort(key=lambda x: x['score'], reverse=True)
    top = scored[:TOP_N]

    # 5. Write output
    output = {
        'generated_at': time.time(),
        'generated_at_iso': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
        'total_candidates': len(candidates),
        'enriched': len(enriched),
        'top_n': len(top),
        'criteria': {
            'positive': [
                'Cross-channel calls (more channels = better)',
                'Freshness (newer = better)',
                'Low FDV / market cap',
                'High + accelerating volume',
                'Transaction count + buy-heavy ratio',
                'Price momentum'
            ],
            'negative': [
                'Heavy sells (>70% in h1)',
                'Only sells in h1 (dev dump)',
                'Stagnant volume (h1 < 1% of h24)',
                'No txns in 6h'
            ]
        },
        'tokens': top
    }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    log.info(f"Wrote top {len(top)} tokens to {OUTPUT_PATH}")

    # Print summary
    log.info(f"\n{'='*60}")
    log.info(f"TOP 10 TOKENS:")
    log.info(f"{'='*60}")
    for i, t in enumerate(top[:10], 1):
        fdv_val = t.get('fdv') or 0
        vol_val = t.get('volume_h24') or 0
        neg = ' ⚠️ ' + ', '.join(t['negatives']) if t['negatives'] else ''
        log.info(f"  #{i} [{t['score']:6.1f}] {t['symbol']:10} {t['chain']}:{t['contract_address'][:20]}... "
                 f"ch={t['channel_count']} FDV=${fdv_val:,.0f} vol24=${vol_val:,.0f}{neg}")

    return {
        'status': 'ok',
        'total_candidates': len(candidates),
        'enriched': len(enriched),
        'top_n': len(top),
        'output_path': str(OUTPUT_PATH)
    }

def calc_buy_ratio(dex: dict) -> Optional[float]:
    txns = dex.get('txns_h24', {})
    buys = txns.get('buys', 0) or 0
    sells = txns.get('sells', 0) or 0
    total = buys + sells
    return round(buys / total, 3) if total > 0 else None

def calc_total_txns(dex: dict, period: str) -> int:
    txns = dex.get(f'txns_{period}', {})
    return (txns.get('buys', 0) or 0) + (txns.get('sells', 0) or 0)

def main():
    start = time.time()
    result = run_screener()
    elapsed = time.time() - start
    log.info(f"\nCompleted in {elapsed:.1f}s: {json.dumps(result)}")
    return 0 if result.get('status') == 'ok' else 1

if __name__ == '__main__':
    sys.exit(main())
