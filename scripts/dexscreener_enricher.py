#!/usr/bin/env python3
"""Dexscreener API enrichment for token data."""
import time
import json
import requests
from typing import Dict, Any, Optional
from pathlib import Path
from smart_money_config import (
    DEXSCREENER_BASE, DEXSCREENER_RATE_LIMIT_DELAY, DATA_DIR, TOKEN_CACHE_PATH
)

class DexscreenerEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.rate_delay = DEXSCREENER_RATE_LIMIT_DELAY
        self.last_request = 0
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        """Load token cache from disk."""
        cache = {}
        if TOKEN_CACHE_PATH.exists():
            try:
                with open(TOKEN_CACHE_PATH, 'r') as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            key = f"{data.get('chain')}:{data.get('token_address')}"
                            cache[key] = data
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                print(f"[Dexscreener] Cache load error: {e}")
        return cache

    def _save_cache_entry(self, data: Dict[str, Any]):
        """Append a single cache entry."""
        try:
            with open(TOKEN_CACHE_PATH, 'a') as f:
                f.write(json.dumps(data) + '\n')
        except Exception as e:
            print(f"[Dexscreener] Cache write error: {e}")

    def _rate_limit(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self.last_request
        if elapsed < self.rate_delay:
            time.sleep(self.rate_delay - elapsed)
        self.last_request = time.time()

    def _get_from_cache(self, chain: str, token_address: str, max_age: int = 3600) -> Optional[Dict[str, Any]]:
        """Retrieve from cache if not too old."""
        key = f"{chain}:{token_address}"
        entry = self.cache.get(key)
        if entry:
            age = time.time() - entry.get('_cached_at', 0)
            if age < max_age:
                return entry
        return None

    def enrich_token(self, chain: str, token_address: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Enrich a token with Dexscreener data.
        Returns dict with token stats or empty dict on failure.
        """
        cache_key = f"{chain}:{token_address}"
        if use_cache:
            cached = self._get_from_cache(chain, token_address)
            if cached:
                print(f"[Dexscreener] Cache hit: {token_address[:10]}...")
                return cached

        self._rate_limit()

        # For EVM chains, use token address directly
        # For Solana, chain param is needed in endpoint
        if chain == 'solana':
            endpoint = f"{DEXSCREENER_BASE}/tokens/{token_address}"
        else:
            # Dexscreener expects chain prefix? Actually endpoint: /latest/dex/tokens/{address} works cross-chain
            endpoint = f"{DEXSCREENER_BASE}/tokens/{token_address}"

        try:
            resp = self.session.get(endpoint, timeout=10)
            if resp.status_code != 200:
                print(f"[Dexscreener] HTTP {resp.status_code} for {token_address}")
                return {}
            data = resp.json()
        except Exception as e:
            print(f"[Dexscreener] Request failed for {token_address}: {e}")
            return {}

        # Parse pairs
        pairs = data.get('pairs', [])
        if not pairs:
            print(f"[Dexscreener] No pairs found for {token_address}")
            return {}

        # Take the pair with highest liquidity (or volume)
        best_pair = max(pairs, key=lambda p: p.get('liquidity', {}).get('usd', 0) or p.get('volume', {}).get('h24', 0))

        result = {
            'token_address': token_address,
            'chain': chain,
            'dex_name': best_pair.get('dexId'),
            'pair_address': best_pair.get('pairAddress'),
            'fdv_usd': best_pair.get('fdv'),
            'liquidity_usd': best_pair.get('liquidity', {}).get('usd'),
            'volume_24h_usd': best_pair.get('volume', {}).get('h24'),
            'price_change_5m': best_pair.get('priceChange', {}).get('m5'),
            'price_change_1h': best_pair.get('priceChange', {}).get('h1'),
            'price_change_24h': best_pair.get('priceChange', {}).get('h24'),
            'age_hours': self._compute_age_hours(best_pair.get('pairCreatedAt')),
            'fee_tier': best_pair.get('fee'),
            'all_pairs': [
                {
                    'dex': p.get('dexId'),
                    'pair_address': p.get('pairAddress'),
                    'fee': p.get('fee'),
                    'liquidity_usd': p.get('liquidity', {}).get('usd')
                }
                for p in pairs[:5]  # top 5
            ],
            '_cached_at': time.time()
        }

        # Cache it
        self._save_cache_entry(result)
        self.cache[cache_key] = result
        fdv_value = result.get('fdv_usd')
        fdv_text = f"{fdv_value:,.2f}" if isinstance(fdv_value, (int, float)) else "N/A"
        print(f"[Dexscreener] Enriched {token_address[:10]}... (FDV: ${fdv_text})")
        return result

    def _compute_age_hours(self, created_at_ms: Optional[int]) -> Optional[float]:
        if not created_at_ms:
            return None
        age_seconds = (time.time() * 1000 - created_at_ms) / 1000
        return round(age_seconds / 3600, 2)

if __name__ == '__main__':
    # Quick test with ANDY token from memory
    enricher = DexscreenerEnricher()
    chain = 'base'
    token = os.getenv('API_KEY', '')
    result = enricher.enrich_token(chain, token)
    print(json.dumps(result, indent=2))
