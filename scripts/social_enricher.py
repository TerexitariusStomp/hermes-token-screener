#!/usr/bin/env python3
"""
Social Signal Enricher - Derive social momentum from available data sources.

Unique advantage: We monitor 62+ Telegram chats in real-time.
The channel call count and mention velocity ARE the social signal.

Sources:
  1. Telegram DB: channel_count, mentions, mention velocity
  2. CoinGecko: sentiment votes (up/down %)
  3. Dexscreener: social links count (websites, twitter, telegram)
"""

import os
import time
import sqlite3
import json
from typing import Dict, Any, Optional, List
from pathlib import Path

DB_PATH = Path.home() / '.hermes' / 'data' / 'central_contracts.db'


class SocialSignalEnricher:
    def __init__(self):
        self.conn = None

    def _get_db(self):
        """Get fresh database connection each time."""
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def enrich(self, chain: str, address: str, dex_data: dict = None) -> Dict[str, Any]:
        """Derive social signals from Telegram DB + CoinGecko sentiment + Dexscreener links."""
        signals = {}

        # Normalize address: lowercase for EVM, as-is for Solana
        if chain.lower() in ('ethereum', 'eth', 'base', 'bsc', 'binance'):
            addr = address.lower()
        else:
            addr = address  # Solana addresses are case-sensitive

        # ── From Telegram DB (our unique data) ──
        tg_signals = self._telegram_signals(chain, addr)
        signals.update(tg_signals)

        # ── From Dexscreener social links ──
        if dex_data:
            social_signals = self._dexscreener_social(dex_data)
            signals.update(social_signals)

        # ── Composite social score (combines all sources) ──
        signals['social_score'] = self._compute_social_score(signals)

        return signals

    def enrich_from_enriched(self, token: dict) -> dict:
        """
        Enrich using already-enriched token data (has CoinGecko fields on it).
        Call this AFTER CoinGecko enricher has run.
        """
        chain = token.get('chain', '')
        addr = token.get('contract_address', '')
        dex = token.get('dex', {})

        # Get base signals
        signals = self.enrich(chain, addr, dex)

        # Now fold in CoinGecko sentiment data
        cg_up = token.get('cg_sentiment_up_pct')
        cg_down = token.get('cg_sentiment_down_pct')

        if cg_up is not None and cg_down is not None:
            total = cg_up + cg_down
            if total > 0:
                signals['social_cg_sentiment_ratio'] = round(cg_up / total, 3)
                signals['social_cg_sentiment_votes'] = int(total)

        # CoinGecko community data
        cg_twitter = token.get('cg_twitter_followers')
        if cg_twitter:
            signals['social_cg_twitter'] = cg_twitter

        cg_reddit = token.get('cg_reddit_subscribers')
        if cg_reddit:
            signals['social_cg_reddit'] = cg_reddit

        # CoinGecko is_meme flag
        if token.get('cg_is_meme'):
            signals['social_cg_is_meme'] = True

        # Recompute social_score with CoinGecko data included
        signals['social_score'] = self._compute_social_score(signals)

        return signals

    def _telegram_signals(self, chain: str, address: str) -> dict:
        """Get social momentum from Telegram call data."""
        conn = self._get_db()
        try:
            cur = conn.cursor()

            # Get channel count, mentions, first/last seen
            cur.execute("""
                SELECT channel_count, channels_seen, mentions,
                       first_seen_at, last_seen_at
                FROM telegram_contracts_unique
                WHERE chain = ? AND contract_address = ?
            """, (chain, address))
            row = cur.fetchone()

            if not row:
                return {}

            now = time.time()
            first_seen = row['first_seen_at']
            last_seen = row['last_seen_at']
            age_hours = (now - first_seen) / 3600 if first_seen else 0
            recency_hours = (now - last_seen) / 3600 if last_seen else 999

            signals = {
                'social_channel_count': row['channel_count'],
                'social_mentions': row['mentions'],
                'social_age_hours': round(age_hours, 1),
                'social_recency_hours': round(recency_hours, 1),
            }

            # Mention velocity: mentions per hour
            if age_hours > 0:
                signals['social_mentions_per_hour'] = round(row['mentions'] / age_hours, 2)

            # Recent momentum
            if recency_hours < 1:
                signals['social_hot'] = True
            elif recency_hours < 6:
                signals['social_warm'] = True
            elif recency_hours > 24:
                signals['social_cold'] = True

            # Channel spread
            channels_seen = row['channels_seen'] or ''
            unique_channels = len(set(channels_seen.split(','))) if channels_seen else 0
            signals['social_unique_channels'] = unique_channels

            # Viral indicator
            if unique_channels > 0 and row['mentions'] > unique_channels * 5:
                signals['social_viral'] = True

            return signals
        finally:
            conn.close()

    def _dexscreener_social(self, dex: dict) -> dict:
        """Extract social link presence from Dexscreener data."""
        signals = {}

        # Dexscreener enricher doesn't currently pass social links
        # but if the raw pair data has them, count them
        info = dex.get('_info', {})
        if info:
            websites = info.get('websites', [])
            socials = info.get('socials', [])
            signals['social_website_count'] = len(websites)
            signals['social_social_count'] = len(socials)
            signals['social_has_website'] = len(websites) > 0
            signals['social_has_twitter'] = any(
                s.get('type', '').lower() == 'twitter'
                for s in socials
            )
            signals['social_has_telegram'] = any(
                s.get('type', '').lower() == 'telegram'
                for s in socials
            )

        return signals

    def _compute_social_score(self, signals: dict) -> float:
        """Compute a 0-100 social momentum score from all sources."""
        score = 0.0

        # ── Telegram signals (0-50) ──

        # Channel count (0-25): 2ch=5, 3ch=10, 5ch=17, 8+=25
        ch = signals.get('social_channel_count', 0)
        if ch >= 8:
            score += 25
        elif ch >= 5:
            score += 17 + (ch - 5) * 2.7
        elif ch >= 3:
            score += 10 + (ch - 3) * 3.5
        elif ch >= 2:
            score += 5

        # Mention velocity (0-15): >5/hr=15, >2/hr=10, >0.5/hr=6
        mph = signals.get('social_mentions_per_hour', 0)
        if mph > 5:
            score += 15
        elif mph > 2:
            score += 10 + (mph - 2) * 1.7
        elif mph > 0.5:
            score += 6 + (mph - 0.5) * 2.7
        elif mph > 0:
            score += mph * 12

        # Recency (0-10): <1hr=10, <6hr=6, <24hr=2
        recency = signals.get('social_recency_hours', 999)
        if recency < 1:
            score += 10
        elif recency < 6:
            score += 6 + (6 - recency) * 0.8
        elif recency < 24:
            score += 2

        # Telegram bonus flags
        if signals.get('social_hot'):
            score *= 1.10
        if signals.get('social_viral'):
            score *= 1.15

        # ── CoinGecko sentiment (0-25) ──

        sentiment_ratio = signals.get('social_cg_sentiment_ratio')
        sentiment_votes = signals.get('social_cg_sentiment_votes', 0)

        if sentiment_ratio is not None and sentiment_votes >= 5:
            # sentiment_ratio: 0.0 = all bearish, 1.0 = all bullish
            if sentiment_ratio > 0.7:
                score += 20 + (sentiment_ratio - 0.7) * 16.7  # 20-25
            elif sentiment_ratio > 0.5:
                score += 10 + (sentiment_ratio - 0.5) * 50  # 10-20
            elif sentiment_ratio > 0.3:
                score += 5 + (sentiment_ratio - 0.3) * 25  # 5-10
            else:
                score -= 10  # bearish penalty

            # Volume of votes = more confident signal
            if sentiment_votes > 50:
                score *= 1.05
            elif sentiment_votes > 100:
                score *= 1.10

        # CoinGecko community presence
        if signals.get('social_cg_twitter', 0) > 10000:
            score += 5
        elif signals.get('social_cg_twitter', 0) > 1000:
            score += 2

        if signals.get('social_cg_reddit', 0) > 1000:
            score += 3

        # Meme coin flag (slight penalty for risk)
        if signals.get('social_cg_is_meme'):
            score *= 0.95

        # ── External links (0-10) ──
        if signals.get('social_has_website'):
            score += 5
        if signals.get('social_has_twitter'):
            score += 3
        if signals.get('social_has_telegram'):
            score += 2

        return round(min(100, max(0, score)), 1)

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        """Enrich a batch of tokens with social signals."""
        enriched = []
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')
            dex = token.get('dex', {})

            social = self.enrich(chain, addr, dex)
            if social:
                enriched.append({**token, **social})
            else:
                enriched.append(token)
        return enriched


if __name__ == '__main__':
    enricher = SocialSignalEnricher()
    # Test with a token that has data
    signals = enricher.enrich('solana', 'acufuwsgvaXrQGNMiohTusi5jcx5RJqEn8MuH48rh4q'.lower())
    print(json.dumps(signals, indent=2))
