#!/usr/bin/env python3
"""
RugCheck enricher - Solana token security analysis.
Free API, no auth required for basic reports.

Provides what GoPlus/De.Fi miss for Solana:
  - Rug score (1=safe, higher=riskier)
  - Risk flags list
  - Rugged flag
  - Insider detection (graph analysis)
  - Insider networks
  - Top holder concentration with insider flags
  - LP lock status
  - Transfer fee detection
  - Creator balance
"""

import os
import time
import requests
from typing import Dict, Any, List
from pathlib import Path

RUGCHECK_BASE = 'https://api.rugcheck.xyz/v1/tokens'
RUGCHECK_DELAY = 0.5


class RugCheckEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.last_request = 0
        self.cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < RUGCHECK_DELAY:
            time.sleep(RUGCHECK_DELAY - elapsed)
        self.last_request = time.time()

    def enrich(self, chain: str, address: str) -> Dict[str, Any]:
        """Enrich a Solana token with RugCheck data."""
        if chain.lower() not in ('solana', 'sol'):
            return {}

        cache_key = address
        if cache_key in self.cache:
            return self.cache[cache_key]

        self._rate_limit()

        try:
            r = self.session.get(f'{RUGCHECK_BASE}/{address}/report', timeout=15)
            if r.status_code != 200:
                return {}
            d = r.json()
        except Exception:
            return {}

        if d.get('score') is None and not d.get('risks'):
            return {}

        result = {}

        # Core security
        result['rugcheck_score'] = d.get('score', 0)
        result['rugcheck_score_normalised'] = d.get('score_normalised', 0)
        result['rugcheck_rugged'] = d.get('rugged', False)
        result['rugcheck_risk_count'] = len(d.get('risks', []))
        result['rugcheck_risks'] = [r.get('name', str(r)) for r in d.get('risks', [])[:5]]

        # Authority
        result['rugcheck_mint_renounced'] = d.get('mintAuthority') is None
        result['rugcheck_freeze_renounced'] = d.get('freezeAuthority') is None

        # Token metadata
        meta = d.get('tokenMeta', {})
        result['rugcheck_mutable'] = meta.get('mutable', True)

        # Holders
        result['rugcheck_total_holders'] = d.get('totalHolders')

        # Top holder concentration
        holders = d.get('topHolders', [])
        if holders:
            top_5 = sum(h.get('pct', 0) for h in holders[:5])
            top_10 = sum(h.get('pct', 0) for h in holders[:10])
            insiders_in_top = sum(1 for h in holders if h.get('insider'))
            result['rugcheck_top_5_holder_pct'] = round(top_5, 2)
            result['rugcheck_top_10_holder_pct'] = round(top_10, 2)
            result['rugcheck_insider_holders'] = insiders_in_top
            result['rugcheck_max_holder_pct'] = round(max(h.get('pct', 0) for h in holders), 2)

        # Insider detection (graph analysis)
        result['rugcheck_insiders_detected'] = d.get('graphInsidersDetected', 0)
        networks = d.get('insiderNetworks', [])
        if networks:
            total_insider_tokens = sum(n.get('tokenAmount', 0) for n in networks)
            result['rugcheck_insider_networks'] = len(networks)
            result['rugcheck_insider_token_amount'] = total_insider_tokens

        # Liquidity
        result['rugcheck_total_liquidity'] = d.get('totalMarketLiquidity')
        result['rugcheck_stable_liquidity'] = d.get('totalStableLiquidity')

        # Transfer fee
        tf = d.get('transferFee', {})
        if tf:
            fee_pct = tf.get('pct', 0)
            result['rugcheck_transfer_fee_pct'] = fee_pct
            if fee_pct > 0:
                result['rugcheck_has_transfer_fee'] = True

        # Creator
        result['rugcheck_creator'] = d.get('creator', '')

        # Launchpad
        launchpad = d.get('launchpad', {})
        if launchpad:
            result['rugcheck_launchpad'] = launchpad.get('name', '')

        # LP lock
        result['rugcheck_lp_lock_status'] = d.get('lockerScanStatus', 'none')
        lp_pct = d.get('lpLockedPct')
        if lp_pct is not None:
            result['rugcheck_lp_locked_pct'] = lp_pct

        self.cache[cache_key] = result
        return result

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        """Enrich batch - only Solana tokens."""
        enriched = []
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')
            if chain.lower() not in ('solana', 'sol'):
                enriched.append(token)
                continue
            data = self.enrich(chain, addr)
            if data:
                enriched.append({**token, **data})
            else:
                enriched.append(token)
        return enriched


if __name__ == '__main__':
    import json
    rc = RugCheckEnricher()
    r = rc.enrich('solana', '3TYgKwkE2Y3rxdw9osLRSpxpXmSC1C1oo19W9KHspump')
    print(json.dumps(r, indent=2))
