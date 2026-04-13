#!/usr/bin/env python3
"""
Surf enricher - market context + per-token social data.

Surf social data available:
  - social-sentiment: sentiment score per project (-1 to +1)
  - social-mindshare: daily social attention volume
  - social-smart-followers: smart follower count history
  - social-ranking: trending projects by mindshare
  - fear-greed: market-wide sentiment index
"""

import os
import json
import subprocess
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime, timedelta

SURF_CLI = os.path.expanduser('~/.local/bin/surf')
SURF_DELAY = 0.5


class SurfEnricher:
    def __init__(self):
        self.last_call = 0
        self._market_ctx = None
        self._token_cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < SURF_DELAY:
            time.sleep(SURF_DELAY - elapsed)
        self.last_call = time.time()

    def _run_cmd(self, args: list) -> Optional[dict]:
        """Run surf CLI and parse JSON output."""
        self._rate_limit()
        try:
            result = subprocess.run(
                [SURF_CLI] + args + ['--json'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout.strip())
        except Exception:
            pass
        return None

    def get_market_context(self) -> Dict[str, Any]:
        """Get market-wide context (cached per run)."""
        if self._market_ctx:
            return self._market_ctx

        signals = {}

        # Fear & Greed
        fg = self._run_cmd(['market-fear-greed'])
        if fg and fg.get('data'):
            latest = fg['data'][0]
            signals['surf_fear_greed'] = latest.get('value')
            signals['surf_fear_greed_class'] = latest.get('classification', '')
            signals['surf_btc_price'] = latest.get('price')

        # Social ranking (trending projects)
        ranking = self._run_cmd(['social-ranking', '--limit', '20', '--time-range', '7d'])
        if ranking and ranking.get('data'):
            trending = {}
            for item in ranking['data']:
                proj = item.get('project', {})
                slug = proj.get('slug', '').lower()
                name = proj.get('name', '').lower()
                if slug:
                    trending[slug] = {
                        'rank': item.get('rank'),
                        'sentiment': item.get('sentiment'),
                        'sentiment_score': item.get('sentiment_score'),
                    }
                if name:
                    trending[name] = trending.get(slug, {})
            signals['surf_trending_projects'] = trending

        self._market_ctx = signals
        return signals

    def get_token_social(self, symbol: str, name: str = '') -> Dict[str, Any]:
        """Get social data for a specific token by symbol or name."""
        cache_key = symbol.lower()
        if cache_key in self._token_cache:
            return self._token_cache[cache_key]

        signals = {}

        # Social sentiment
        query = symbol if symbol else name
        if query:
            sentiment = self._run_cmd(['social-sentiment', '--q', query])
            if sentiment and sentiment.get('data'):
                d = sentiment['data']
                score = d.get('sentiment_score')
                if score is not None:
                    signals['surf_social_sentiment'] = round(score, 4)
                    signals['surf_social_project'] = d.get('project_name', '')

        # Social mindshare (recent trend)
        if query:
            mindshare = self._run_cmd([
                'social-mindshare', '--q', query,
                '--interval', '1d',
                '--from', (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
            ])
            if mindshare and mindshare.get('data'):
                points = mindshare['data']
                if len(points) >= 2:
                    latest = points[-1].get('value', 0)
                    prev = points[-2].get('value', 0)
                    if prev > 0:
                        change = (latest - prev) / prev
                        signals['surf_mindshare_change'] = round(change, 4)
                    signals['surf_mindshare_latest'] = latest
                elif points:
                    signals['surf_mindshare_latest'] = points[-1].get('value', 0)

        # Check if token is in trending projects
        ctx = self.get_market_context()
        trending = ctx.get('surf_trending_projects', {})
        for key in [symbol.lower(), name.lower()]:
            if key and key in trending:
                t = trending[key]
                signals['surf_trending_rank'] = t.get('rank')
                signals['surf_trending_sentiment'] = t.get('sentiment')
                break

        self._token_cache[cache_key] = signals
        return signals

    def enrich_token(self, chain: str, address: str, symbol: str = '', name: str = '') -> Dict[str, Any]:
        """Full enrichment: market context + token social data."""
        signals = {}

        # Market context (applies to all)
        ctx = self.get_market_context()
        signals.update({k: v for k, v in ctx.items() if not isinstance(v, dict)})

        # Per-token social data
        if symbol or name:
            social = self.get_token_social(symbol, name)
            signals.update(social)

        return signals

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        """Enrich batch with market context + per-token social data."""
        ctx = self.get_market_context()
        enriched = []
        for token in tokens:
            merged = {**token}

            # Market context
            merged.update({k: v for k, v in ctx.items() if not isinstance(v, dict)})

            # Per-token social
            symbol = token.get('symbol') or token.get('cg_symbol', '')
            name = token.get('name') or token.get('cg_name', '')
            if symbol or name:
                social = self.get_token_social(symbol, name)
                merged.update(social)

            enriched.append(merged)
        return enriched


if __name__ == '__main__':
    s = SurfEnricher()
    # Test with BONK
    r = s.enrich_token('solana', '', symbol='BONK', name='Bonk')
    print(json.dumps(r, indent=2))
