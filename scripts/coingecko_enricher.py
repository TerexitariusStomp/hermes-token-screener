#!/usr/bin/env python3
"""
CoinGecko enricher - broader market data for tokens.
Provides: sentiment, categories, ATH data, market context.
Works with contract address lookup on free tier.
"""

import os
import time
import json
import requests
from typing import Dict, Any, Optional, List
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')

COINGECKO_BASE = 'https://api.coingecko.com/api/v3'
COINGECKO_DELAY = 1.5  # free tier: ~10-30 req/min

# Chain name mapping for CoinGecko
CG_CHAINS = {
    'ethereum': 'ethereum', 'eth': 'ethereum',
    'solana': 'solana',
    'base': 'base',
    'binance': 'binance-smart-chain', 'bsc': 'binance-smart-chain',
    'polygon': 'polygon-pos',
    'arbitrum': 'arbitrum-one',
    'avalanche': 'avalanche',
    'optimism': 'optimistic-ethereum',
}


class CoinGeckoEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.last_request = 0
        self.cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < COINGECKO_DELAY:
            time.sleep(COINGECKO_DELAY - elapsed)
        self.last_request = time.time()

    def enrich(self, chain: str, address: str) -> Dict[str, Any]:
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        cg_chain = CG_CHAINS.get(chain.lower())
        if not cg_chain:
            return {}

        self._rate_limit()

        try:
            r = self.session.get(
                f'{COINGECKO_BASE}/coins/{cg_chain}/contract/{address.lower()}',
                params={
                    'localization': 'false',
                    'tickers': 'true',
                    'community_data': 'true',
                    'developer_data': 'false',
                },
                timeout=15
            )
            if r.status_code != 200:
                return {}
            d = r.json()
        except Exception:
            return {}

        md = d.get('market_data', {})
        result = {
            'cg_id': d.get('id'),
            'cg_name': d.get('name'),
            'cg_symbol': d.get('symbol', '').upper(),
            'cg_price_usd': self._float(md.get('current_price', {}).get('usd')),
            'cg_market_cap': self._float(md.get('market_cap', {}).get('usd')),
            'cg_volume_24h': self._float(md.get('total_volume', {}).get('usd')),
            'cg_fdv': self._float(md.get('fully_diluted_valuation', {}).get('usd')),
            'cg_ath': self._float(md.get('ath', {}).get('usd')),
            'cg_ath_change_pct': self._float(md.get('ath_change_percentage', {}).get('usd')),
            'cg_ath_date': md.get('ath_date', {}).get('usd', '')[:10],
            'cg_price_change_24h_pct': self._float(md.get('price_change_percentage_24h')),
            'cg_price_change_7d_pct': self._float(md.get('price_change_percentage_7d')),
            'cg_price_change_30d_pct': self._float(md.get('price_change_percentage_30d')),
            'cg_total_supply': self._float(md.get('total_supply')),
            'cg_max_supply': self._float(md.get('max_supply')),
            'cg_circulating_supply': self._float(md.get('circulating_supply')),
            'cg_sentiment_up_pct': self._float(d.get('sentiment_votes_up_percentage')),
            'cg_sentiment_down_pct': self._float(d.get('sentiment_votes_down_percentage')),
            'cg_categories': d.get('categories', [])[:5],
            'cg_liquidity_score': self._float(d.get('liquidity_score')),
            'cg_is_listed': True,
        }

        # Community data
        cd = d.get('community_data', {})
        tw = cd.get('twitter_followers')
        if tw:
            result['cg_twitter_followers'] = tw
        rd = cd.get('reddit_subscribers')
        if rd:
            result['cg_reddit_subscribers'] = rd

        # Detect if it's a meme coin
        cats = [c.lower() for c in result['cg_categories']]
        result['cg_is_meme'] = any('meme' in c for c in cats)

        # Exchange listings (from tickers)
        if d.get('tickers'):
            tickers = d['tickers']
            result['cg_exchange_count'] = len(tickers)
            major_exchanges = {'Binance', 'Coinbase Exchange', 'Kraken', 'OKX', 'Bybit', 'Gate', 'KuCoin', 'HTX'}
            listed_on = set(t['market']['name'] for t in tickers if t.get('market', {}).get('name') in major_exchanges)
            result['cg_major_exchange_listings'] = list(listed_on)
            result['cg_major_exchange_count'] = len(listed_on)
            result['cg_listed_on_binance'] = 'Binance' in listed_on
            result['cg_listed_on_coinbase'] = 'Coinbase Exchange' in listed_on

            # Top exchange by volume
            exchange_vol = {}
            for t in tickers:
                name = t.get('market', {}).get('name', '?')
                vol = t.get('converted_volume', {}).get('usd', 0) or 0
                exchange_vol[name] = exchange_vol.get(name, 0) + vol
            if exchange_vol:
                top_ex = max(exchange_vol, key=exchange_vol.get)
                result['cg_top_exchange'] = top_ex
                result['cg_top_exchange_vol'] = round(exchange_vol[top_ex], 2)

        self.cache[cache_key] = result
        return result

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        enriched = []
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')
            cg = self.enrich(chain, addr)
            if cg:
                enriched.append({**token, **cg})
            else:
                enriched.append(token)
        return enriched

    @staticmethod
    def _float(v) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None


if __name__ == '__main__':
    cg = CoinGeckoEnricher()
    r = cg.enrich('solana', 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263')
    print(json.dumps(r, indent=2))
