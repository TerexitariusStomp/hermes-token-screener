#!/usr/bin/env python3
"""
De.Fi GraphQL API enricher for token security analysis.

Uses De.Fi public GraphQL API for contract security scanning.
Supports: Ethereum (1), Binance (2), Solana (12), Base (49), and more.
"""

import os
import time
import json
import requests
from typing import Dict, Any, Optional, List
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')

DEFI_ENDPOINT = 'https://public-api.de.fi/graphql'
DEFI_API_KEY = os.getenv('DEFI_API_KEY', 'os.getenv('DEFI_API_KEY', '')')
DEFI_DELAY = 3.0  # rate limit: 20 requests/min for scanner endpoints

# Map our chain names to De.Fi chain IDs
# De.Fi uses its own chain IDs, NOT standard EVM chain IDs
# Discovered via API introspection and testing
DEFI_CHAIN_IDS = {
    'ethereum': 1, 'eth': 1,
    'binance': 2, 'bsc': 2,
    'solana': 12,
    'base': 49,
    # Not yet verified: polygon, arbitrum, optimism
}


class DefiEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': DEFI_API_KEY,
            'Content-Type': 'application/json',
        })
        self.last_request = 0
        self.cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < DEFI_DELAY:
            time.sleep(DEFI_DELAY - elapsed)
        self.last_request = time.time()

    def _query(self, query: str) -> Optional[dict]:
        """Execute a GraphQL query against De.Fi."""
        self._rate_limit()
        try:
            resp = self.session.post(DEFI_ENDPOINT, json={'query': query}, timeout=20)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if 'errors' in data:
                return None
            return data.get('data')
        except Exception:
            return None

    def enrich(self, chain: str, address: str) -> Dict[str, Any]:
        """Enrich a single token with De.Fi security data."""
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        chain_id = DEFI_CHAIN_IDS.get(chain.lower())
        if not chain_id:
            return {}

        addr_lower = address.lower()

        # Single combined GraphQL query
        query = """
        query {
          scannerProject(where: { address: "%s", chainId: %d }) {
            name txCount outdatedCompiler whitelisted
            coreIssues { scwTitle scwDescription }
            stats { low medium high critical total percentage scammed }
          }
          scannerHolderAnalysis(where: { address: "%s", chainId: %d }) {
            topHolders { address balance percent isContract }
            totalHolders
          }
        }
        """ % (addr_lower, chain_id, addr_lower, chain_id)

        data = self._query(query)
        if not data:
            return {}

        enriched = {}

        # Parse scannerProject
        project = data.get('scannerProject') or {}
        if project.get('name'):
            enriched['defi_project_name'] = project['name']
            enriched['defi_whitelisted'] = project.get('whitelisted', False)
            enriched['defi_outdated_compiler'] = project.get('outdatedCompiler', False)

            # Count issues by severity
            stats = project.get('stats') or {}
            if stats:
                enriched['defi_issues_critical'] = stats.get('critical', 0)
                enriched['defi_issues_high'] = stats.get('high', 0)
                enriched['defi_issues_medium'] = stats.get('medium', 0)
                enriched['defi_issues_low'] = stats.get('low', 0)
                enriched['defi_issues_total'] = stats.get('total', 0)
                enriched['defi_scammed'] = stats.get('scammed', False)

            # Core issues
            core_issues = [i.get('scwTitle') for i in (project.get('coreIssues') or []) if i.get('scwTitle')]
            enriched['defi_core_issues'] = core_issues

        # Parse scannerHolderAnalysis
        holders = data.get('scannerHolderAnalysis') or {}
        if holders.get('topHolders'):
            top = holders['topHolders']
            enriched['defi_total_holders'] = holders.get('totalHolders')
            top_10_pct = sum(h.get('percent', 0) for h in top[:10])
            enriched['defi_top_10_holder_pct'] = round(top_10_pct, 2)

            # Count contract vs EOA holders
            contract_holders = sum(1 for h in top if h.get('isContract'))
            enriched['defi_contract_holder_count'] = contract_holders

        if enriched:
            self.cache[cache_key] = enriched
        return enriched

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        """Enrich a batch of tokens. Only processes De.Fi supported chains."""
        enriched = []
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')

            if chain.lower() not in DEFI_CHAIN_IDS:
                enriched.append(token)
                continue

            defi_data = self.enrich(chain, addr)
            if defi_data:
                enriched.append({**token, **defi_data})
            else:
                enriched.append(token)
        return enriched


if __name__ == '__main__':
    enricher = DefiEnricher()
    result = enricher.enrich('ethereum', '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48')
    print(json.dumps(result, indent=2))
