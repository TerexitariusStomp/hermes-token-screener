#!/usr/bin/env python3
"""
GoPlus Security API enricher for token screening.

Uses GoPlus v2 public API (api.gopluslabs.io) for EVM chains.
Solana support is limited (returns OK but mostly empty for meme coins).
"""

import time
import json
import requests
from typing import Dict, Any, Optional, List

GOPLUS_V2_BASE = 'https://api.gopluslabs.io/api/v2/token_security'
GOPLUS_DELAY = 1.0

GOPLUS_CHAIN_IDS = {
    'ethereum': '1', 'eth': '1', 'bsc': '56', 'arbitrum': '42161',
    'polygon': '137', 'base': '8453', 'optimism': '10',
    'avalanche': '43114', 'solana': 'solana', 'fantom': '250',
}


class GoPlusEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.last_request = 0
        self.cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < GOPLUS_DELAY:
            time.sleep(GOPLUS_DELAY - elapsed)
        self.last_request = time.time()

    def enrich(self, chain: str, address: str) -> Dict[str, Any]:
        """Enrich a single token with GoPlus security data."""
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        chain_id = GOPLUS_CHAIN_IDS.get(chain.lower())
        if not chain_id or chain_id == 'solana':
            return {}

        self._rate_limit()

        # Try primary chain
        enriched = self._fetch_and_parse(chain_id, address)

        # If ethereum-labeled token returned nothing, also try Base
        # (address extractor defaults 0x addresses to "ethereum")
        if not enriched and chain.lower() == 'ethereum':
            enriched = self._fetch_and_parse('8453', address)

        if enriched:
            self.cache[cache_key] = enriched
        return enriched

    def _fetch_and_parse(self, chain_id: str, address: str) -> Dict[str, Any]:
        """Fetch from GoPlus API and parse into enriched dict."""
        try:
            resp = self.session.get(
                f'{GOPLUS_V2_BASE}/{chain_id}',
                params={'contract_addresses': address},
                timeout=15
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
            if data.get('code') != 1:
                return {}
        except Exception:
            return {}

        result = data.get('result', {})
        info = result.get(address.lower(), {})
        if not info:
            return {}

        return self._parse_security_data(info)

    def _parse_security_data(self, info: dict) -> Dict[str, Any]:
        """Parse GoPlus response into enriched security fields."""
        enriched = {
            'goplus_is_honeypot': self._bool(info.get('is_honeypot')),
            'goplus_buy_tax': self._float(info.get('buy_tax')),
            'goplus_sell_tax': self._float(info.get('sell_tax')),
            'goplus_transfer_tax': self._float(info.get('transfer_tax')),
            'goplus_holder_count': self._int(info.get('holder_count')),
            'goplus_is_mintable': self._bool(info.get('is_mintable')),
            'goplus_is_proxy': self._bool(info.get('is_proxy')),
            'goplus_is_open_source': self._bool(info.get('is_open_source')),
            'goplus_transfer_pausable': self._bool(info.get('transfer_pausable')),
            'goplus_cannot_buy': self._bool(info.get('cannot_buy')),
            'goplus_cannot_sell_all': self._bool(info.get('cannot_sell_all')),
            'goplus_slippage_modifiable': self._bool(info.get('slippage_modifiable')),
            'goplus_owner_can_change_balance': self._bool(info.get('owner_can_change_balance')),
            'goplus_can_take_back_ownership': self._bool(info.get('can_take_back_ownership')),
            'goplus_is_blacklisted': self._bool(info.get('is_blacklisted')),
            'goplus_is_whitelisted': self._bool(info.get('is_whitelisted')),
            'goplus_is_trust_list': self._bool(info.get('trust_list')),
            'goplus_creator_address': info.get('creator_address'),
            'goplus_creator_balance': self._float(info.get('creator_balance')),
            'goplus_creator_percent': self._float(info.get('creator_percent')),
            'goplus_lp_holder_count': self._int(info.get('lp_holder_count')),
            'goplus_lp_total_supply': self._float(info.get('lp_total_supply')),
            'goplus_is_in_dex': self._bool(info.get('is_in_dex')),
            'goplus_is_in_cex': (
                info.get('is_in_cex', {}).get('listed') == '1'
                if isinstance(info.get('is_in_cex'), dict) else False
            ),
            'goplus_honeypot_same_creator': self._bool(info.get('honeypot_with_same_creator')),
        }

        # Top holder concentration
        holders = info.get('holders', [])
        if holders:
            top_10_pct = sum(self._float(h.get('percent', 0)) or 0 for h in holders[:10])
            enriched['goplus_top_10_holder_pct'] = round(top_10_pct * 100, 2)

            creator = info.get('creator_address', '')
            if creator:
                enriched['goplus_creator_in_top_20'] = any(
                    h.get('address', '').lower() == creator.lower()
                    for h in holders[:20]
                )

        return enriched

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        """Enrich a batch of tokens."""
        enriched = []
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')
            goplus_data = self.enrich(chain, addr)
            if goplus_data:
                enriched.append({**token, **goplus_data})
            else:
                enriched.append(token)
        return enriched

    @staticmethod
    def _bool(v) -> bool:
        if v is None:
            return False
        return str(v) in ('1', 'true', 'True', 'yes')

    @staticmethod
    def _float(v) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _int(v) -> Optional[int]:
        if v is None:
            return None
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None


if __name__ == '__main__':
    enricher = GoPlusEnricher()
    result = enricher.enrich('base', '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913')
    print(json.dumps(result, indent=2))
