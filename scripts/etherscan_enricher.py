#!/usr/bin/env python3
"""
Etherscan V2 enricher - contract verification and creator data.
For Base chain tokens. Verified contract = strong legitimacy signal.
"""

import os
import time
import requests
from typing import Dict, Any, List
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')

ETHERSCAN_KEY = os.getenv('ETHERSCAN_API_KEY', 'os.getenv('ETHERSCAN_API_KEY', '')')
ETHERSCAN_V2 = 'https://api.etherscan.io/v2/api'
ETHERSCAN_DELAY = 0.25

# Chain name -> Etherscan chain ID
ETHSCAN_CHAIN_IDS = {
    'ethereum': 1, 'eth': 1,
    'base': 8453,
    'binance': 56, 'bsc': 56,
    'polygon': 137,
    'arbitrum': 42161,
    'optimism': 10,
    'avalanche': 43114,
}


class EtherscanEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.last_request = 0
        self.cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < ETHERSCAN_DELAY:
            time.sleep(ETHERSCAN_DELAY - elapsed)
        self.last_request = time.time()

    def enrich(self, chain: str, address: str) -> Dict[str, Any]:
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        chain_id = ETHSCAN_CHAIN_IDS.get(chain.lower())
        if not chain_id:
            return {}

        self._rate_limit()

        # Get contract source code (verification status)
        contract_info = self._get_contract(chain_id, address)
        if not contract_info:
            return {}

        result = {
            'etherscan_verified': bool(contract_info.get('SourceCode')),
            'etherscan_contract_name': contract_info.get('ContractName', ''),
            'etherscan_compiler': contract_info.get('CompilerVersion', ''),
            'etherscan_is_proxy': contract_info.get('IsProxy') == '1',
            'etherscan_optimization': contract_info.get('OptimizationUsed') == '1',
            'etherscan_evm_version': contract_info.get('EVMVersion', ''),
            'etherscan_license': contract_info.get('LicenseType', ''),
        }

        if contract_info.get('Implementation'):
            result['etherscan_implementation'] = contract_info['Implementation']

        # Source code length = more thorough verification
        source_len = len(contract_info.get('SourceCode', ''))
        if source_len > 0:
            result['etherscan_source_length'] = source_len
            result['etherscan_is_verified'] = True

        # Get first transaction (creator)
        self._rate_limit()
        creator = self._get_creator(chain_id, address)
        if creator:
            result['etherscan_creator'] = creator

        self.cache[cache_key] = result
        return result

    def _get_contract(self, chain_id: int, address: str) -> dict:
        try:
            r = self.session.get(ETHERSCAN_V2, params={
                'chainid': chain_id,
                'module': 'contract',
                'action': 'getsourcecode',
                'address': address,
                'apikey': ETHERSCAN_KEY,
            }, timeout=10)
            d = r.json()
            if d.get('result') and isinstance(d['result'], list) and d['result']:
                return d['result'][0]
        except Exception:
            pass
        return {}

    def _get_creator(self, chain_id: int, address: str) -> str:
        try:
            r = self.session.get(ETHERSCAN_V2, params={
                'chainid': chain_id,
                'module': 'account',
                'action': 'txlist',
                'address': address,
                'page': 1,
                'offset': 1,
                'sort': 'asc',
                'apikey': ETHERSCAN_KEY,
            }, timeout=10)
            d = r.json()
            if d.get('result') and isinstance(d['result'], list) and d['result']:
                return d['result'][0].get('from', '')
        except Exception:
            pass
        return ''

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        enriched = []
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')
            eth_data = self.enrich(chain, addr)
            if eth_data:
                enriched.append({**token, **eth_data})
            else:
                enriched.append(token)
        return enriched


if __name__ == '__main__':
    e = EtherscanEnricher()
    r = e.enrich('base', '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913')
    print(r)
