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

import os
import sys
import json
import time
import sqlite3
import logging
import subprocess
import math
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = Path.home() / '.hermes' / 'data' / 'central_contracts.db'
OUTPUT_PATH = Path.home() / '.hermes' / 'data' / 'token_screener' / 'top100.json'
LOG_FILE = Path.home() / '.hermes' / 'logs' / 'token_screener.log'

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

SELL_RATIO_THRESHOLD = 0.70
STAGNANT_VOLUME_RATIO = 0.01
NO_ACTIVITY_HOURS = 6

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
log = logging.getLogger('token_enricher')

# ══════════════════════════════════════════════════════════════════════════════
# ENRICHER BASE — resilient try/bypass pattern
# ══════════════════════════════════════════════════════════════════════════════

class EnricherResult:
    """Track enrichment status per layer."""
    def __init__(self):
        self.layers: Dict[str, dict] = {}  # name -> {ok, count, total, error, elapsed}

    def record(self, name: str, ok: bool, enriched: int, total: int,
               error: str = '', elapsed: float = 0):
        self.layers[name] = {
            'ok': ok, 'enriched': enriched, 'total': total,
            'error': error, 'elapsed': round(elapsed, 1)
        }
        if ok:
            log.info(f"  {name}: {enriched}/{total} ({elapsed:.1f}s)")
        else:
            log.warning(f"  {name}: FAILED ({error}) - bypassed")

    def summary(self) -> List[str]:
        lines = []
        for name, s in self.layers.items():
            status = "[OK]" if s['ok'] else "[SKIP]"
            lines.append(f"  {status} {name:20s} {s['enriched']:3d}/{s['total']} ({s['elapsed']}s)")
            if s['error']:
                lines[-1] += f" err={s['error'][:50]}"
        return lines


def _float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _bool(v) -> bool:
    if v is None:
        return False
    return str(v) in ('1', 'true', 'True', 'yes')


def _int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 0: Dexscreener (REQUIRED)
# ══════════════════════════════════════════════════════════════════════════════

DEXSCREENER_BASE = 'https://api.dexscreener.com/latest/dex'
DEXSCREENER_DELAY = float(os.getenv('DEXSCREENER_RATE_LIMIT_DELAY', '1.0'))

class DexscreenerEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.last_request = 0

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < DEXSCREENER_DELAY:
            time.sleep(DEXSCREENER_DELAY - elapsed)
        self.last_request = time.time()

    def enrich(self, address: str) -> dict:
        self._rate_limit()
        try:
            resp = self.session.get(f'{DEXSCREENER_BASE}/tokens/{address}', timeout=10)
            if resp.status_code != 200:
                return {}
            data = resp.json()
        except Exception:
            return {}

        pairs = data.get('pairs', [])
        if not pairs:
            return {}

        best = max(pairs, key=lambda p: (p.get('liquidity', {}).get('usd', 0) or 0))
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

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        results = []
        for i, token in enumerate(tokens):
            addr = token['contract_address']
            if (i + 1) % 50 == 0:
                log.info(f"  Dexscreener {i+1}/{len(tokens)}...")
            dex_data = self.enrich(addr)
            if dex_data:
                results.append({**token, 'dex': dex_data})
        return results, len(results)

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1: Surf (market context + social)
# ══════════════════════════════════════════════════════════════════════════════

SURF_CLI = shutil.which('surf') or str(Path.home() / '.local' / 'bin' / 'surf')
SURF_DELAY = 0.5

class SurfEnricher:
    def __init__(self):
        self.last_call = 0
        self._market_ctx = None

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < SURF_DELAY:
            time.sleep(SURF_DELAY - elapsed)
        self.last_call = time.time()

    def _run_cmd(self, args: list) -> Optional[dict]:
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
        if self._market_ctx:
            return self._market_ctx

        signals = {}
        fg = self._run_cmd(['market-fear-greed'])
        if fg and fg.get('data'):
            latest = fg['data'][0]
            signals['surf_fear_greed'] = latest.get('value')
            signals['surf_btc_price'] = latest.get('price')

        ranking = self._run_cmd(['social-ranking', '--limit', '20', '--time-range', '7d'])
        if ranking and ranking.get('data'):
            trending = {}
            for item in ranking['data']:
                proj = item.get('project', {})
                slug = proj.get('slug', '').lower()
                name = proj.get('name', '').lower()
                if slug:
                    trending[slug] = {'rank': item.get('rank'), 'sentiment_score': item.get('sentiment_score')}
                if name and name not in trending:
                    trending[name] = trending[slug]
            signals['surf_trending_projects'] = trending

        self._market_ctx = signals
        return signals

    def _get_token_social(self, symbol: str, name: str = '') -> dict:
        signals = {}
        query = symbol or name
        if not query:
            return signals

        sentiment = self._run_cmd(['social-sentiment', '--q', query])
        if sentiment and sentiment.get('data'):
            score = sentiment['data'].get('sentiment_score')
            if score is not None:
                signals['surf_social_sentiment'] = round(score, 4)

        mindshare = self._run_cmd([
            'social-mindshare', '--q', query, '--interval', '1d',
            '--from', (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
        ])
        if mindshare and mindshare.get('data'):
            points = mindshare['data']
            if len(points) >= 2:
                latest = points[-1].get('value', 0)
                prev = points[-2].get('value', 0)
                if prev > 0:
                    signals['surf_mindshare_change'] = round((latest - prev) / prev, 4)

        ctx = self.get_market_context()
        trending = ctx.get('surf_trending_projects', {})
        for key in [symbol.lower(), name.lower()]:
            if key and key in trending:
                signals['surf_trending_rank'] = trending[key].get('rank')
                break

        return signals

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        ctx = self.get_market_context()
        enriched_count = 0
        for token in tokens:
            for k, v in ctx.items():
                if not isinstance(v, dict):
                    token[k] = v
            symbol = token.get('symbol') or token.get('cg_symbol', '')
            name = token.get('name') or token.get('cg_name', '')
            if symbol or name:
                social = self._get_token_social(symbol, name)
                token.update(social)
                if social:
                    enriched_count += 1
        return tokens, enriched_count


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2: GoPlus (EVM security)
# ══════════════════════════════════════════════════════════════════════════════

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
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        chain_id = GOPLUS_CHAIN_IDS.get(chain.lower())
        if not chain_id or chain_id == 'solana':
            return {}

        self._rate_limit()
        enriched = self._fetch(chain_id, address)

        # Fallback: ethereum-labeled tokens might be on Base
        if not enriched and chain.lower() == 'ethereum':
            enriched = self._fetch('8453', address)

        if enriched:
            self.cache[cache_key] = enriched
        return enriched

    def _fetch(self, chain_id: str, address: str) -> dict:
        try:
            resp = self.session.get(
                f'{GOPLUS_V2_BASE}/{chain_id}',
                params={'contract_addresses': address}, timeout=15
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
            if data.get('code') != 1:
                return {}
        except Exception:
            return {}

        info = data.get('result', {}).get(address.lower(), {})
        if not info:
            return {}

        holders = info.get('holders', [])
        top_10_pct = round(sum(_float(h.get('percent', 0)) or 0 for h in holders[:10]) * 100, 2) if holders else None

        return {
            'goplus_is_honeypot': _bool(info.get('is_honeypot')),
            'goplus_buy_tax': _float(info.get('buy_tax')),
            'goplus_sell_tax': _float(info.get('sell_tax')),
            'goplus_holder_count': _int(info.get('holder_count')),
            'goplus_is_mintable': _bool(info.get('is_mintable')),
            'goplus_is_open_source': _bool(info.get('is_open_source')),
            'goplus_transfer_pausable': _bool(info.get('transfer_pausable')),
            'goplus_cannot_buy': _bool(info.get('cannot_buy')),
            'goplus_cannot_sell_all': _bool(info.get('cannot_sell_all')),
            'goplus_slippage_modifiable': _bool(info.get('slippage_modifiable')),
            'goplus_owner_can_change_balance': _bool(info.get('owner_can_change_balance')),
            'goplus_can_take_back_ownership': _bool(info.get('can_take_back_ownership')),
            'goplus_is_trust_list': _bool(info.get('trust_list')),
            'goplus_creator_percent': _float(info.get('creator_percent')),
            'goplus_is_in_cex': (info.get('is_in_cex', {}).get('listed') == '1'
                                if isinstance(info.get('is_in_cex'), dict) else False),
            'goplus_honeypot_same_creator': _bool(info.get('honeypot_with_same_creator')),
            'goplus_top_10_holder_pct': top_10_pct,
        }

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')
            data = self.enrich(chain, addr)
            if data:
                token.update(data)
                count += 1
        return tokens, count

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3: RugCheck (Solana security)
# ══════════════════════════════════════════════════════════════════════════════

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
        if chain.lower() not in ('solana', 'sol'):
            return {}
        if address in self.cache:
            return self.cache[address]

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

        result = {
            'rugcheck_score': d.get('score', 0),
            'rugcheck_rugged': d.get('rugged', False),
            'rugcheck_risk_count': len(d.get('risks', [])),
            'rugcheck_risks': [r.get('name', str(r)) for r in d.get('risks', [])[:5]],
            'rugcheck_mint_renounced': d.get('mintAuthority') is None,
            'rugcheck_freeze_renounced': d.get('freezeAuthority') is None,
            'rugcheck_total_holders': d.get('totalHolders'),
            'rugcheck_insiders_detected': d.get('graphInsidersDetected', 0),
        }

        holders = d.get('topHolders', [])
        if holders:
            result['rugcheck_top_10_holder_pct'] = round(sum(h.get('pct', 0) for h in holders[:10]), 2)
            result['rugcheck_max_holder_pct'] = round(max(h.get('pct', 0) for h in holders), 2)
            result['rugcheck_insider_holders'] = sum(1 for h in holders if h.get('insider'))

        meta = d.get('tokenMeta', {})
        result['rugcheck_mutable'] = meta.get('mutable', True)

        tf = d.get('transferFee', {})
        if tf and tf.get('pct', 0) > 0:
            result['rugcheck_has_transfer_fee'] = True
            result['rugcheck_transfer_fee_pct'] = tf.get('pct', 0)

        self.cache[address] = result
        return result

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            data = self.enrich(token.get('chain', ''), token.get('contract_address', ''))
            if data:
                token.update(data)
                count += 1
        return tokens, count


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4: Etherscan (contract verification)
# ══════════════════════════════════════════════════════════════════════════════

ETHERSCAN_KEY = os.getenv('ETHERSCAN_API_KEY', '3VY4WXTCKJWC3PQHDTK38MVR73AMPV5A4S')
ETHERSCAN_V2 = 'https://api.etherscan.io/v2/api'
ETHERSCAN_DELAY = 0.25
ETHSCAN_CHAIN_IDS = {
    'ethereum': 1, 'eth': 1, 'base': 8453,
    'binance': 56, 'bsc': 56, 'polygon': 137,
    'arbitrum': 42161, 'optimism': 10, 'avalanche': 43114,
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
        try:
            r = self.session.get(ETHERSCAN_V2, params={
                'chainid': chain_id, 'module': 'contract', 'action': 'getsourcecode',
                'address': address, 'apikey': ETHERSCAN_KEY,
            }, timeout=10)
            d = r.json()
            if not (d.get('result') and isinstance(d['result'], list) and d['result']):
                return {}
            info = d['result'][0]
        except Exception:
            return {}

        result = {
            'etherscan_verified': bool(info.get('SourceCode')),
            'etherscan_contract_name': info.get('ContractName', ''),
            'etherscan_is_proxy': info.get('IsProxy') == '1',
        }
        if info.get('SourceCode'):
            result['etherscan_is_verified'] = True
            result['etherscan_source_length'] = len(info['SourceCode'])

        self.cache[cache_key] = result
        return result

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            data = self.enrich(token.get('chain', ''), token.get('contract_address', ''))
            if data:
                token.update(data)
                count += 1
        return tokens, count


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 5: De.Fi (security analysis)
# ══════════════════════════════════════════════════════════════════════════════

DEFI_ENDPOINT = 'https://public-api.de.fi/graphql'
DEFI_API_KEY = os.getenv('DEFI_API_KEY', '')
DEFI_DELAY = 3.0
DEFI_CHAIN_IDS = {'ethereum': 1, 'eth': 1, 'binance': 2, 'bsc': 2, 'solana': 12, 'base': 49}

class DefiEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'X-Api-Key': DEFI_API_KEY, 'Content-Type': 'application/json'})
        self.last_request = 0
        self.cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < DEFI_DELAY:
            time.sleep(DEFI_DELAY - elapsed)
        self.last_request = time.time()

    def enrich(self, chain: str, address: str) -> Dict[str, Any]:
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        chain_id = DEFI_CHAIN_IDS.get(chain.lower())
        if not chain_id:
            return {}

        self._rate_limit()
        addr_lower = address.lower()
        query = """
        query {
          scannerProject(where: { address: "%s", chainId: %d }) {
            name whitelisted
            coreIssues { scwTitle }
            stats { low medium high critical total percentage scammed }
          }
          scannerHolderAnalysis(where: { address: "%s", chainId: %d }) {
            topHolders { address percent isContract }
            totalHolders
          }
        }
        """ % (addr_lower, chain_id, addr_lower, chain_id)

        try:
            resp = self.session.post(DEFI_ENDPOINT, json={'query': query}, timeout=20)
            if resp.status_code != 200:
                return {}
            data = resp.json()
            if 'errors' in data:
                return {}
            data = data.get('data')
        except Exception:
            return {}

        if not data:
            return {}

        enriched = {}
        project = data.get('scannerProject') or {}
        if project.get('name'):
            enriched['defi_project_name'] = project['name']
            enriched['defi_whitelisted'] = project.get('whitelisted', False)
            stats = project.get('stats') or {}
            if stats:
                enriched['defi_issues_critical'] = stats.get('critical', 0)
                enriched['defi_issues_high'] = stats.get('high', 0)
                enriched['defi_issues_total'] = stats.get('total', 0)
                enriched['defi_scammed'] = stats.get('scammed', False)
            core = [i.get('scwTitle') for i in (project.get('coreIssues') or []) if i.get('scwTitle')]
            enriched['defi_core_issues'] = core

        holders = data.get('scannerHolderAnalysis') or {}
        if holders.get('topHolders'):
            top = holders['topHolders']
            enriched['defi_top_10_holder_pct'] = round(sum(h.get('percent', 0) for h in top[:10]), 2)

        if enriched:
            self.cache[cache_key] = enriched
        return enriched

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            chain = token.get('chain', '')
            if chain.lower() not in DEFI_CHAIN_IDS:
                continue
            data = self.enrich(chain, token.get('contract_address', ''))
            if data:
                token.update(data)
                count += 1
        return tokens, count

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 6: Derived Security (computed from Dexscreener data, no API needed)
# ══════════════════════════════════════════════════════════════════════════════

SOLANA_RPC = 'https://api.mainnet-beta.solana.com'
RPC_DELAY = 0.5

class DerivedSecurityAnalyzer:
    def __init__(self):
        self.session = requests.Session()
        self.last_rpc = 0

    def _rpc_call(self, method: str, params: list) -> Optional[dict]:
        elapsed = time.time() - self.last_rpc
        if elapsed < RPC_DELAY:
            time.sleep(RPC_DELAY - elapsed)
        self.last_rpc = time.time()
        try:
            resp = self.session.post(SOLANA_RPC, json={
                'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params
            }, timeout=15)
            if resp.status_code == 200:
                return resp.json().get('result')
        except Exception:
            pass
        return None

    def analyze(self, chain: str, address: str, dex: dict) -> Dict[str, Any]:
        signals = {}

        # From Dexscreener
        txns = dex.get('txns_h24', {})
        buys = txns.get('buys', 0) or 0
        sells = txns.get('sells', 0) or 0
        total = buys + sells
        if total > 0:
            buy_ratio = buys / total
            signals['derived_buy_ratio'] = round(buy_ratio, 3)
            if buy_ratio > 0.85:
                signals['derived_suspect_buy_inflate'] = True

        # Volume momentum
        v24 = dex.get('volume_h24', 0) or 0
        v6 = dex.get('volume_h6', 0) or 0
        v1 = dex.get('volume_h1', 0) or 0
        v5 = dex.get('volume_m5', 0) or 0

        if v24 > 0:
            if v6 * 4 < v24 * 0.1:
                signals['derived_volume_dying'] = True
            elif v6 * 4 > v24 * 2:
                signals['derived_volume_accelerating'] = True

        if v5 == 0 and v1 == 0:
            signals['derived_no_recent_activity'] = True

        # Liquidity risk
        liq = dex.get('liquidity_usd', 0) or 0
        fdv = dex.get('fdv', 0) or 0
        if fdv > 0:
            liq_ratio = liq / fdv
            signals['derived_liq_fdv_ratio'] = round(liq_ratio, 4)
            if liq_ratio < 0.02:
                signals['derived_liq_risk'] = 'critical'
            elif liq_ratio < 0.05:
                signals['derived_liq_risk'] = 'high'

        # Price rug detection
        pc_h1 = dex.get('price_change_h1')
        pc_h6 = dex.get('price_change_h6')
        if pc_h1 is not None:
            if pc_h1 < -50:
                signals['derived_massive_dump'] = True
            if pc_h1 < -30 and (v1 or 0) > 1000:
                signals['derived_possible_rug'] = True
            if pc_h6 is not None and pc_h6 > 100 and pc_h1 < -20:
                signals['derived_pump_and_dump'] = True

        # Brand new
        age = dex.get('age_hours')
        if age is not None and age < 0.5:
            signals['derived_brand_new'] = True

        # Solana on-chain
        if chain.lower() == 'solana':
            mint_info = self._rpc_call('getAccountInfo', [address, {'encoding': 'jsonParsed'}])
            if mint_info and mint_info.get('value'):
                parsed = mint_info['value'].get('data', {}).get('parsed', {})
                if parsed.get('type') == 'mint':
                    info = parsed.get('info', {})
                    signals['derived_has_mint_authority'] = info.get('mintAuthority') is not None
                    signals['derived_has_freeze_authority'] = info.get('freezeAuthority') is not None

            largest = self._rpc_call('getTokenLargestAccounts', [address])
            if largest and largest.get('value'):
                accounts = largest['value']
                total_ui = sum(float(a.get('uiAmount', 0) or 0) for a in accounts)
                if total_ui > 0:
                    top_10 = sum(float(a.get('uiAmount', 0) or 0) for a in accounts[:10])
                    signals['derived_top_10_holder_pct'] = round(top_10 / total_ui * 100, 2)
                    max_pct = max(float(a.get('uiAmount', 0) or 0) / total_ui for a in accounts) * 100
                    signals['derived_max_holder_pct'] = round(max_pct, 2)

        return signals

    def analyze_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            signals = self.analyze(token.get('chain', ''), token.get('contract_address', ''), token.get('dex', {}))
            if signals:
                token.update(signals)
                count += 1
        return tokens, count


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 7: CoinGecko (market data + exchange listings)
# ══════════════════════════════════════════════════════════════════════════════

COINGECKO_BASE = 'https://api.coingecko.com/api/v3'
COINGECKO_DELAY = 1.5
CG_CHAINS = {
    'ethereum': 'ethereum', 'eth': 'ethereum', 'solana': 'solana',
    'base': 'base', 'binance': 'binance-smart-chain', 'bsc': 'binance-smart-chain',
    'polygon': 'polygon-pos', 'arbitrum': 'arbitrum-one',
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
                params={'localization': 'false', 'tickers': 'true', 'community_data': 'true'},
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
            'cg_symbol': d.get('symbol', '').upper(),
            'cg_price_usd': _float(md.get('current_price', {}).get('usd')),
            'cg_market_cap': _float(md.get('market_cap', {}).get('usd')),
            'cg_fdv': _float(md.get('fully_diluted_valuation', {}).get('usd')),
            'cg_ath_change_pct': _float(md.get('ath_change_percentage', {}).get('usd')),
            'cg_price_change_24h_pct': _float(md.get('price_change_percentage_24h')),
            'cg_sentiment_up_pct': _float(d.get('sentiment_votes_up_percentage')),
            'cg_sentiment_down_pct': _float(d.get('sentiment_votes_down_percentage')),
            'cg_categories': d.get('categories', [])[:5],
            'cg_is_listed': True,
        }

        cats = [c.lower() for c in result['cg_categories']]
        result['cg_is_meme'] = any('meme' in c for c in cats)

        # Exchange listings
        if d.get('tickers'):
            major = {'Binance', 'Coinbase Exchange', 'Kraken', 'OKX', 'Bybit', 'Gate', 'KuCoin'}
            listed = set(t['market']['name'] for t in d['tickers'] if t.get('market', {}).get('name') in major)
            result['cg_major_exchange_count'] = len(listed)
            result['cg_listed_on_binance'] = 'Binance' in listed
            result['cg_listed_on_coinbase'] = 'Coinbase Exchange' in listed

        self.cache[cache_key] = result
        return result

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            data = self.enrich(token.get('chain', ''), token.get('contract_address', ''))
            if data:
                token.update(data)
                count += 1
        return tokens, count

# ══════════════════════════════════════════════════════════════════════════════
# LAYER 8: GMGN (dev conviction, smart money, bot detection)
# ══════════════════════════════════════════════════════════════════════════════

GMGN_CLI = str(Path.home() / '.hermes' / 'gmgn-cli' / 'dist' / 'index.js')
GMGN_API_KEY = os.getenv('GMGN_API_KEY', '')
GMGN_DELAY = 0.5
CHAIN_MAP = {
    'solana': 'sol', 'sol': 'sol', 'base': 'base',
    'ethereum': 'base', 'eth': 'base', 'binance': 'bsc', 'bsc': 'bsc',
}

class GMGNEnricher:
    _NODE_BIN = None

    def __init__(self):
        self.last_call = 0
        self.cache = {}

    def _find_node(self) -> str:
        if GMGNEnricher._NODE_BIN is not None:
            return GMGNEnricher._NODE_BIN
        node = shutil.which('node')
        if node:
            GMGNEnricher._NODE_BIN = node
            return node
        for candidate in [
            str(Path.home() / '.local' / 'bin' / 'node'),
            '/usr/local/bin/node', '/usr/bin/node',
        ]:
            if Path(candidate).is_file():
                GMGNEnricher._NODE_BIN = candidate
                return candidate
        GMGNEnricher._NODE_BIN = 'node'
        return 'node'

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < GMGN_DELAY:
            time.sleep(GMGN_DELAY - elapsed)
        self.last_call = time.time()

    def _run_cmd(self, args: list) -> Optional[dict]:
        self._rate_limit()
        try:
            env = {**os.environ, 'GMGN_API_KEY': GMGN_API_KEY}
            result = subprocess.run(
                [self._find_node(), GMGN_CLI] + args,
                capture_output=True, text=True, timeout=30, env=env
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout.strip())
        except FileNotFoundError:
            log.error("gmgn-cli: node binary not found")
        except Exception:
            pass
        return None

    def enrich(self, chain: str, address: str) -> Dict[str, Any]:
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        gmgn_chain = CHAIN_MAP.get(chain.lower())
        if not gmgn_chain or not GMGN_API_KEY:
            return {}

        info = self._run_cmd(['token', 'info', '--chain', gmgn_chain, '--address', address, '--raw'])
        security = self._run_cmd(['token', 'security', '--chain', gmgn_chain, '--address', address, '--raw'])

        if not info and not security:
            return {}

        result = {}
        if info:
            result['gmgn_holder_count'] = info.get('holder_count')
            result['gmgn_liquidity'] = _float(info.get('liquidity'))
            result['gmgn_price'] = _float(info.get('price'))
            result['gmgn_ath_price'] = _float(info.get('ath_price'))
            result['gmgn_total_supply'] = _float(info.get('total_supply'))

            dev = info.get('dev', {})
            if dev:
                result['gmgn_creator_status'] = dev.get('creator_token_status', '')
                result['gmgn_dev_hold'] = dev.get('creator_token_status') == 'creator_hold'
                result['gmgn_top_10_holder_rate'] = _float(dev.get('top_10_holder_rate'))
                result['gmgn_cto_flag'] = dev.get('cto_flag', 0) == 1
                tw_count = dev.get('twitter_create_token_count', 0)
                result['gmgn_dev_token_count'] = tw_count
                if tw_count > 5:
                    result['gmgn_dev_token_farmer'] = True

            stat = info.get('stat', {})
            if stat:
                result['gmgn_bot_degen_rate'] = _float(stat.get('bot_degen_rate'))
                result['gmgn_fresh_wallet_rate'] = _float(stat.get('fresh_wallet_rate'))
                result['gmgn_dev_team_hold_rate'] = _float(stat.get('dev_team_hold_rate'))
                result['gmgn_private_vault_rate'] = _float(stat.get('private_vault_hold_rate'))
                result['gmgn_top_entrapment'] = _float(stat.get('top_entrapment_trader_percentage'))
                result['gmgn_top_bundler'] = _float(stat.get('top_bundler_trader_percentage'))
                result['gmgn_top_rat'] = _float(stat.get('top_rat_trader_percentage'))

            tags = info.get('wallet_tags_stat', {})
            if tags:
                result['gmgn_smart_wallets'] = tags.get('smart_wallets', 0)
                result['gmgn_renowned_wallets'] = tags.get('renowned_wallets', 0)
                result['gmgn_sniper_wallets'] = tags.get('sniper_wallets', 0)
                result['gmgn_rat_traders'] = tags.get('rat_trader_wallets', 0)
                result['gmgn_whale_wallets'] = tags.get('whale_wallets', 0)
                result['gmgn_bundler_wallets'] = tags.get('bundler_wallets', 0)

            link = info.get('link', {})
            if link:
                result['gmgn_has_twitter'] = bool(link.get('twitter_username'))
                result['gmgn_has_website'] = bool(link.get('website'))

        if security:
            result['gmgn_renounced_mint'] = security.get('renounced_mint', False)
            result['gmgn_renounced_freeze'] = security.get('renounced_freeze_account', False)
            result['gmgn_burn_status'] = security.get('burn_status', 'unknown')
            result['gmgn_burn_ratio'] = _float(security.get('burn_ratio'))
            result['gmgn_honeypot'] = security.get('honeypot', 0) == 1
            result['gmgn_buy_tax'] = _float(security.get('buy_tax'))
            result['gmgn_sell_tax'] = _float(security.get('sell_tax'))
            result['gmgn_is_locked'] = security.get('lock_summary', {}).get('is_locked', False)

        self.cache[cache_key] = result
        return result

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            data = self.enrich(token.get('chain', ''), token.get('contract_address', ''))
            if data:
                token.update(data)
                count += 1
        return tokens, count


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 9: Social Signals (Telegram DB, no API needed)
# ══════════════════════════════════════════════════════════════════════════════

class SocialSignalEnricher:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path

    def _get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def enrich_from_enriched(self, token: dict) -> dict:
        chain = token.get('chain', '')
        addr = token.get('contract_address', '')
        signals = {}

        # Telegram DB signals
        conn = self._get_db()
        try:
            cur = conn.cursor()
            if chain.lower() in ('ethereum', 'eth', 'base', 'bsc', 'binance'):
                lookup_addr = addr.lower()
            else:
                lookup_addr = addr

            cur.execute("""
                SELECT channel_count, channels_seen, mentions,
                       first_seen_at, last_seen_at
                FROM telegram_contracts_unique
                WHERE chain = ? AND contract_address = ?
            """, (chain, lookup_addr))
            row = cur.fetchone()
            if row:
                now = time.time()
                first_seen = row['first_seen_at']
                last_seen = row['last_seen_at']
                age_hours = (now - first_seen) / 3600 if first_seen else 0
                recency_hours = (now - last_seen) / 3600 if last_seen else 999

                signals['social_channel_count'] = row['channel_count']
                signals['social_mentions'] = row['mentions']
                signals['social_recency_hours'] = round(recency_hours, 1)

                if age_hours > 0:
                    signals['social_mentions_per_hour'] = round(row['mentions'] / age_hours, 2)

                if recency_hours < 1:
                    signals['social_hot'] = True
                elif recency_hours > 24:
                    signals['social_cold'] = True

                channels_seen = row['channels_seen'] or ''
                unique = len(set(channels_seen.split(','))) if channels_seen else 0
                if unique > 0 and row['mentions'] > unique * 5:
                    signals['social_viral'] = True
        finally:
            conn.close()

        # CoinGecko sentiment
        cg_up = token.get('cg_sentiment_up_pct')
        cg_down = token.get('cg_sentiment_down_pct')
        if cg_up is not None and cg_down is not None:
            total = cg_up + cg_down
            if total > 0:
                signals['social_cg_sentiment_ratio'] = round(cg_up / total, 3)

        # Composite social score
        signals['social_score'] = self._compute_score(signals)
        return signals

    def _compute_score(self, signals: dict) -> float:
        score = 0.0

        # Telegram signals (0-50)
        ch = signals.get('social_channel_count', 0)
        if ch >= 8: score += 25
        elif ch >= 5: score += 17 + (ch - 5) * 2.7
        elif ch >= 3: score += 10 + (ch - 3) * 3.5
        elif ch >= 2: score += 5

        mph = signals.get('social_mentions_per_hour', 0)
        if mph > 5: score += 15
        elif mph > 2: score += 10 + (mph - 2) * 1.7
        elif mph > 0.5: score += 6 + (mph - 0.5) * 2.7
        elif mph > 0: score += mph * 12

        recency = signals.get('social_recency_hours', 999)
        if recency < 1: score += 10
        elif recency < 6: score += 6
        elif recency < 24: score += 2

        if signals.get('social_hot'): score *= 1.10
        if signals.get('social_viral'): score *= 1.15

        # CoinGecko sentiment (0-25)
        ratio = signals.get('social_cg_sentiment_ratio')
        if ratio is not None:
            if ratio > 0.7: score += 20 + (ratio - 0.7) * 16.7
            elif ratio > 0.5: score += 10 + (ratio - 0.5) * 50
            elif ratio > 0.3: score += 5 + (ratio - 0.3) * 25
            else: score -= 10

        return round(min(100, max(0, score)), 1)


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 10: Zerion (token market data + wallet portfolio)
# ══════════════════════════════════════════════════════════════════════════════

import base64

ZERION_KEY = os.getenv('ZERION_API_KEY', '')
ZERION_DELAY = 1.0

class ZerionEnricher:
    def __init__(self):
        self.session = requests.Session()
        if ZERION_KEY:
            auth = base64.b64encode((ZERION_KEY + ":").encode()).decode()
            self.session.headers.update({
                'Authorization': f'Basic {auth}',
                'accept': 'application/json',
            })
        self.last_request = 0
        self.cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_request
        if elapsed < ZERION_DELAY:
            time.sleep(ZERION_DELAY - elapsed)
        self.last_request = time.time()

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        self._rate_limit()
        try:
            r = self.session.get(f'https://api.zerion.io/v1{endpoint}', params=params or {}, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(5)
                return None
        except Exception:
            pass
        return None

    def enrich_token(self, chain: str, address: str, symbol: str = '') -> Dict[str, Any]:
        """Get token market data from Zerion."""
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        if not ZERION_KEY:
            return {}

        # Search by symbol or address
        query = symbol if symbol else address
        data = self._get('/fungibles', {'filter[search_query]': query})
        if not data:
            return {}

        # Find the right token matching our chain
        target_chain = chain.lower()
        for item in data.get('data', []):
            attrs = item.get('attributes', {})
            impls = attrs.get('implementations', [])

            # Check if this token exists on our chain
            chain_match = any(
                i.get('chain_id', '').lower() == target_chain
                for i in impls
            )
            # Or match by contract address
            addr_match = any(
                i.get('address', '').lower() == address.lower()
                for i in impls
            )

            if chain_match or addr_match:
                md = attrs.get('market_data', {})
                result = {
                    'zerion_name': attrs.get('name'),
                    'zerion_symbol': attrs.get('symbol'),
                    'zerion_verified': attrs.get('flags', {}).get('verified', False),
                    'zerion_price': _float(md.get('price')),
                    'zerion_market_cap': _float(md.get('market_cap')),
                    'zerion_fdv': _float(md.get('fully_diluted_valuation')),
                    'zerion_total_supply': _float(md.get('total_supply')),
                    'zerion_circulating_supply': _float(md.get('circulating_supply')),
                }

                # Price changes
                changes = md.get('changes', {})
                if isinstance(changes, dict):
                    for period in ['1h', '1d', '1w']:
                        ch = changes.get(f'percent_{period}')
                        if ch is not None:
                            result[f'zerion_change_{period}'] = _float(ch)

                # External links
                links = attrs.get('external_links', [])
                if isinstance(links, list):
                    for link in links:
                        ltype = link.get('type', '')
                        if ltype == 'twitter':
                            result['zerion_twitter'] = link.get('url', '')
                        elif ltype == 'coingecko':
                            result['zerion_coingecko_url'] = link.get('url', '')

                # Chain count
                result['zerion_chain_count'] = len(impls)

                self.cache[cache_key] = result
                return result

        return {}

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            symbol = token.get('symbol') or token.get('cg_symbol', '')
            data = self.enrich_token(
                token.get('chain', ''),
                token.get('contract_address', ''),
                symbol,
            )
            if data:
                token.update(data)
                count += 1
        return tokens, count

    def get_wallet_portfolio(self, address: str) -> Dict[str, Any]:
        """Get wallet portfolio value and positions from Zerion."""
        if not ZERION_KEY:
            return {}

        data = self._get(f'/wallets/{address}/portfolio')
        if not data:
            return {}

        attrs = data.get('data', {}).get('attributes', {})
        total = attrs.get('total', {})
        changes = attrs.get('changes', {})

        result = {
            'zerion_portfolio_value': _float(total.get('positions', 0)),
            'zerion_24h_change_abs': _float(changes.get('absolute_1d')) if changes else None,
            'zerion_24h_change_pct': _float(changes.get('percent_1d')) if changes else None,
        }

        # Distribution
        dist = attrs.get('positions_distribution_by_type', {})
        if dist:
            result['zerion_deposited'] = _float(dist.get('deposited', 0))
            result['zerion_staked'] = _float(dist.get('staked', 0))
            result['zerion_borrowed'] = _float(dist.get('borrowed', 0))

        return result


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 11: CoinStats (risk score + market data via MCP)
# ══════════════════════════════════════════════════════════════════════════════

COINSTATS_API_KEY = os.getenv('COINSTATS_API_KEY', '')
COINSTATS_MCP_DELAY = 2.0

class CoinStatsEnricher:
    def __init__(self):
        self.last_call = 0
        self.cache = {}
        self._node = None

    def _find_node(self):
        if self._node:
            return self._node
        self._node = shutil.which('node') or '/usr/local/bin/node'
        return self._node

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < COINSTATS_MCP_DELAY:
            time.sleep(COINSTATS_MCP_DELAY - elapsed)
        self.last_call = time.time()

    def _call_mcp(self, tool: str, args: dict) -> Optional[Any]:
        """Call CoinStats MCP tool via npx subprocess."""
        if not COINSTATS_API_KEY:
            return None

        self._rate_limit()
        try:
            import tempfile
            req = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args}
            })

            env = {**os.environ, 'COINSTATS_API_KEY': COINSTATS_API_KEY}
            result = subprocess.run(
                ['npx', '-y', '@coinstats/coinstats-mcp'],
                input=req, capture_output=True, text=True, timeout=30, env=env
            )

            # Parse JSON-RPC response from stdout (skip MCP startup line)
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.startswith('{'):
                    try:
                        resp = json.loads(line)
                        content = resp.get('result', {}).get('content', [])
                        if content:
                            return json.loads(content[0].get('text', '{}'))
                    except (json.JSONDecodeError, KeyError):
                        pass
        except Exception:
            pass
        return None

    def enrich_token(self, symbol: str, address: str = '') -> Dict[str, Any]:
        """Get token risk score and market data from CoinStats."""
        cache_key = symbol or address
        if cache_key in self.cache:
            return self.cache[cache_key]

        if not COINSTATS_API_KEY:
            return {}

        # Search by symbol
        data = self._call_mcp('get-coins', {
            'symbol': symbol,
            'limit': 1,
            'includeRiskScore': 'true',
        })

        if not data or not data.get('result'):
            return {}

        coin = data['result'][0]

        result = {
            'cs_id': coin.get('id'),
            'cs_rank': coin.get('rank'),
            'cs_price': _float(coin.get('price')),
            'cs_market_cap': _float(coin.get('marketCap')),
            'cs_volume': _float(coin.get('volume')),
            'cs_fdv': _float(coin.get('fullyDilutedValuation')),
            'cs_available_supply': _float(coin.get('availableSupply')),
            'cs_total_supply': _float(coin.get('totalSupply')),
            'cs_price_change_1h': _float(coin.get('priceChange1h')),
            'cs_price_change_1d': _float(coin.get('priceChange1d')),
            'cs_price_change_1w': _float(coin.get('priceChange1w')),
            'cs_risk_score': _float(coin.get('riskScore')),
            'cs_liquidity_score': _float(coin.get('liquidityScore')),
            'cs_volatility_score': _float(coin.get('volatilityScore')),
            'cs_avg_change': _float(coin.get('avgChange')),
            'cs_twitter_url': coin.get('twitterUrl', ''),
        }

        # Contract addresses
        addrs = coin.get('contractAddresses', [])
        if addrs:
            result['cs_chain_count'] = len(addrs)

        self.cache[cache_key] = result
        return result

    def enrich_batch(self, tokens: List[dict]) -> Tuple[List[dict], int]:
        count = 0
        for token in tokens:
            symbol = token.get('symbol') or token.get('cg_symbol', '')
            if not symbol:
                continue
            data = self.enrich_token(symbol, token.get('contract_address', ''))
            if data:
                token.update(data)
                count += 1
        return tokens, count

    # get_wallet_balance removed — CoinStats wallet API unreliable

# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_token(token: dict) -> Tuple[float, List[str], List[str]]:
    dex = token.get('dex', {})
    score = 0.0
    positives = []
    negatives = []

    # 1. Cross-channel calls + social momentum (0-35)
    social_score = token.get('social_score', 0)
    channel_count = token.get('channel_count', 0)
    if social_score:
        score += social_score * 0.35
        if token.get('social_hot'):
            positives.append(f"social HOT (ch={channel_count})")
        elif channel_count >= 5:
            positives.append(f"called in {channel_count} channels")
    else:
        score += min(25, 5 + (math.log2(max(1, channel_count)) * 7))

    # 2. Freshness (0-15)
    age_hours = dex.get('age_hours')
    if age_hours is not None:
        if age_hours < 6: freshness = 15
        elif age_hours < 24: freshness = 12
        elif age_hours < 72: freshness = 8
        elif age_hours < 168: freshness = 4
        else: freshness = 1
        score += freshness

    # 3. Low FDV (0-15)
    fdv = dex.get('fdv') or dex.get('market_cap')
    if fdv and fdv > 0:
        if fdv < 50_000: fdv_score = 15
        elif fdv < 200_000: fdv_score = 12
        elif fdv < 1_000_000: fdv_score = 9
        elif fdv < 5_000_000: fdv_score = 6
        elif fdv < 50_000_000: fdv_score = 3
        else: fdv_score = 1
        score += fdv_score
        positives.append(f"FDV ${fdv:,.0f}")

    # 4. Volume (0-20)
    vol_h24 = dex.get('volume_h24', 0) or 0
    vol_h1 = dex.get('volume_h1', 0) or 0
    vol_m5 = dex.get('volume_m5', 0) or 0

    if vol_h24 > 0:
        if vol_h24 > 500_000: vol_abs = 10
        elif vol_h24 > 100_000: vol_abs = 8
        elif vol_h24 > 25_000: vol_abs = 6
        elif vol_h24 > 5_000: vol_abs = 4
        elif vol_h24 > 1_000: vol_abs = 2
        else: vol_abs = 1

        vol_h1_ratio = (vol_h1 * 24) / vol_h24 if vol_h24 > 0 else 0
        if vol_h1_ratio > 3: vol_accel = 10
        elif vol_h1_ratio > 1.5: vol_accel = 7
        elif vol_h1_ratio > 0.5: vol_accel = 4
        elif vol_m5 > 0: vol_accel = 2
        else: vol_accel = 0

        score += vol_abs + vol_accel
        positives.append(f"vol24 ${vol_h24:,.0f}")

    # 5. Transaction activity + buy ratio (0-15)
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
        if total_h24 > 500: txn_score = 7
        elif total_h24 > 100: txn_score = 5
        elif total_h24 > 30: txn_score = 3
        else: txn_score = 1

        buy_ratio = buys_h24 / total_h24
        if buy_ratio > 0.7: buy_score = 8
        elif buy_ratio > 0.6: buy_score = 6
        elif buy_ratio > 0.5: buy_score = 4
        elif buy_ratio > 0.4: buy_score = 2
        else: buy_score = 0

        score += txn_score + buy_score

    # 6. Price momentum (0-10)
    pc_h1 = dex.get('price_change_h1')
    pc_h6 = dex.get('price_change_h6')
    pc_h24 = dex.get('price_change_h24')
    momentum = 0
    if pc_h1 is not None and pc_h1 > 0: momentum += 3
    if pc_h6 is not None and pc_h6 > 0: momentum += 3
    if pc_h24 is not None and pc_h24 > 10: momentum += 4
    elif pc_h24 is not None and pc_h24 > 0: momentum += 2
    score += momentum

    # ── STEEP DECLINE PENALTIES (price collapse = unlikely to recover) ──

    # Rapid crash in h1 (steep sell-off, rug in progress)
    if pc_h1 is not None:
        if pc_h1 < -60:
            score *= 0.1
            negatives.append(f"CRASH h1 ({pc_h1:+.0f}%)")
        elif pc_h1 < -40:
            score *= 0.2
            negatives.append(f"steep decline h1 ({pc_h1:+.0f}%)")
        elif pc_h1 < -25:
            score *= 0.5
            negatives.append(f"heavy decline h1 ({pc_h1:+.0f}%)")

    # Sustained decline over h6 (bleeding out)
    if pc_h6 is not None:
        if pc_h6 < -70:
            score *= 0.1
            negatives.append(f"DEAD h6 ({pc_h6:+.0f}%)")
        elif pc_h6 < -50:
            score *= 0.2
            negatives.append(f"crashed h6 ({pc_h6:+.0f}%)")
        elif pc_h6 < -30:
            score *= 0.5
            negatives.append(f"declining h6 ({pc_h6:+.0f}%)")

    # 24h collapse
    if pc_h24 is not None:
        if pc_h24 < -80:
            score *= 0.1
            negatives.append(f"DEAD h24 ({pc_h24:+.0f}%)")
        elif pc_h24 < -50:
            score *= 0.3
            negatives.append(f"collapsed h24 ({pc_h24:+.0f}%)")

    # Volume dying + price declining = death spiral
    vol_h1 = dex.get('volume_h1', 0) or 0
    vol_h24 = dex.get('volume_h24', 0) or 0
    if vol_h24 > 0 and vol_h1 < vol_h24 * 0.005:  # h1 < 0.5% of h24
        if pc_h6 is not None and pc_h6 < -10:
            score *= 0.3
            negatives.append("death spiral (vol+dying+declining)")

    # ── Multipliers from enrichers ──

    # DISQUALIFIERS (score = 0, return early)
    if token.get('gmgn_honeypot'):
        return 0, [], ["HONEYPOT (GMGN)"]
    if token.get('goplus_is_honeypot'):
        return 0, [], ["HONEYPOT (GoPlus)"]
    if token.get('rugcheck_rugged'):
        return 0, [], ["RUGGED (RugCheck)"]
    if token.get('defi_scammed'):
        return 0, [], ["SCAMMED (De.Fi)"]

    # Etherscan
    if token.get('etherscan_verified'):
        score *= 1.20
        positives.append(f"VERIFIED ({token.get('etherscan_contract_name', '')})")

    # RugCheck
    rc_score = token.get('rugcheck_score', 0)
    if rc_score > 10: score *= 0.2
    elif rc_score > 5: score *= 0.5
    elif rc_score > 3: score *= 0.7

    rc_risks = token.get('rugcheck_risk_count', 0)
    if rc_risks > 3: score *= 0.3
    elif rc_risks > 0: score *= max(0.5, 1 - rc_risks * 0.15)

    if token.get('rugcheck_mint_renounced') is False:
        score *= 0.3
        negatives.append("mint not renounced (RugCheck)")
    if token.get('rugcheck_freeze_renounced') is False:
        score *= 0.5
        negatives.append("freeze not renounced (RugCheck)")

    insiders = token.get('rugcheck_insiders_detected', 0)
    if insiders > 20: score *= 0.4
    elif insiders > 5: score *= 0.7

    rc_top10 = token.get('rugcheck_top_10_holder_pct')
    if rc_top10 is not None and rc_top10 > 80: score *= 0.3
    elif rc_top10 is not None and rc_top10 > 60: score *= 0.6

    # GMGN
    if token.get('gmgn_dev_hold'):
        score *= 1.25
        positives.append("DEV STILL HOLDING")
    elif token.get('gmgn_creator_status') == 'creator_sold':
        score *= 0.5
        negatives.append("dev dumped")

    dev_rate = token.get('gmgn_dev_team_hold_rate')
    if dev_rate is not None:
        if dev_rate > 0.05: score *= 1.10
        elif dev_rate == 0: score *= 0.8

    if token.get('gmgn_renounced_mint') is True:
        score *= 1.10
    elif token.get('gmgn_renounced_mint') is False:
        score *= 0.3

    burn = token.get('gmgn_burn_status')
    if burn == 'burn': score *= 1.15

    bot_rate = token.get('gmgn_bot_degen_rate')
    if bot_rate is not None and bot_rate > 0.3:
        score *= max(0.3, 1 - bot_rate)

    smart = token.get('gmgn_smart_wallets', 0)
    if smart > 20:
        score *= 1.15
        positives.append(f"{smart} smart wallets")
    elif smart > 5:
        score *= 1.08

    if token.get('gmgn_dev_token_farmer'):
        score *= 0.6

    if token.get('gmgn_cto_flag'):
        score *= 1.10
        positives.append("CTO")

    # GoPlus
    buy_tax = token.get('goplus_buy_tax')
    sell_tax = token.get('goplus_sell_tax')
    if buy_tax is not None and buy_tax > 0.10: score *= max(0.2, 1 - buy_tax)
    if sell_tax is not None and sell_tax > 0.10: score *= max(0.2, 1 - sell_tax)

    if token.get('goplus_is_mintable'):
        score *= 0.5
        negatives.append("MINTABLE")
    if token.get('goplus_owner_can_change_balance'):
        score *= 0.2

    top_10_pct = token.get('goplus_top_10_holder_pct')
    if top_10_pct is not None and top_10_pct > 70:
        score *= 0.3 if top_10_pct > 85 else 0.5

    if token.get('goplus_is_trust_list'):
        score *= 1.15

    # De.Fi
    critical = token.get('defi_issues_critical', 0) or 0
    if critical > 0:
        score *= max(0.1, 0.5 ** critical)

    # Derived
    if token.get('derived_has_mint_authority'):
        score *= 0.3
        negatives.append("HAS MINT AUTHORITY")
    if token.get('derived_has_freeze_authority'):
        score *= 0.5

    max_pct = token.get('derived_max_holder_pct')
    if max_pct is not None and max_pct > 50:
        score *= 0.2
    elif max_pct is not None and max_pct > 25:
        score *= 0.5

    if token.get('derived_volume_dying'): score *= 0.4
    if token.get('derived_no_recent_activity'): score *= 0.3
    if token.get('derived_massive_dump'): score *= 0.2
    if token.get('derived_possible_rug'): score *= 0.1
    if token.get('derived_pump_and_dump'): score *= 0.3

    if token.get('derived_liq_risk') == 'critical': score *= 0.4
    elif token.get('derived_liq_risk') == 'high': score *= 0.7

    if token.get('derived_brand_new'): score *= 0.6
    if token.get('derived_suspect_buy_inflate'): score *= 0.7
    if token.get('derived_activity_hot'): score *= 1.05
    if token.get('derived_volume_accelerating'): score *= 1.05

    # CoinGecko
    if token.get('cg_is_listed'):
        score *= 1.08
        positives.append("CoinGecko listed")
    if token.get('cg_listed_on_binance'):
        score *= 1.10
        positives.append("BINANCE")
    elif token.get('cg_listed_on_coinbase'):
        score *= 1.08
        positives.append("COINBASE")

    # Surf
    surf_sent = token.get('surf_social_sentiment')
    if surf_sent is not None:
        if surf_sent > 0.3: score *= 1.10
        elif surf_sent < -0.2: score *= 0.85

    trending_rank = token.get('surf_trending_rank')
    if trending_rank is not None and trending_rank <= 5:
        score *= 1.15
        positives.append(f"TRENDING #{trending_rank}")

    # Volume penalties
    if sells_h1 > 0 and buys_h1 == 0:
        score *= 0.1
        negatives.append("ONLY SELLS in h1")
    elif sells_h1 > 0:
        sell_ratio = sells_h1 / (buys_h1 + sells_h1)
        if sell_ratio > SELL_RATIO_THRESHOLD:
            score *= 0.3
            negatives.append(f"HEAVY SELLS ({sell_ratio:.0%})")

    if vol_h24 > 0 and vol_h1 > 0:
        if vol_h1 < vol_h24 * STAGNANT_VOLUME_RATIO:
            score *= 0.5
            negatives.append("stagnant volume")

    total_h6 = buys_h6 + sells_h6
    if total_h6 == 0 and age_hours and age_hours > 1:
        score *= 0.4
        negatives.append("no txns in 6h")


    # ── Zerion Token Signals ──
    if token.get('zerion_verified'):
        score *= 1.05
        positives.append("Zerion verified")
    if token.get('zerion_chain_count', 0) > 5:
        score *= 1.03

    # ── CoinStats Risk Score ──
    cs_risk = token.get('cs_risk_score')
    if cs_risk is not None:
        if cs_risk > 80:
            score *= 0.5
            negatives.append(f"CoinStats risk {cs_risk:.0f}")
        elif cs_risk > 60:
            score *= 0.7
            negatives.append(f"CoinStats risk {cs_risk:.0f}")
        elif cs_risk < 30:
            score *= 1.05
            positives.append(f"CoinStats low risk ({cs_risk:.0f})")

    cs_liq = token.get('cs_liquidity_score')
    if cs_liq is not None and cs_liq < 10:
        score *= 0.8
        negatives.append(f"low CoinStats liquidity ({cs_liq:.0f})")

    cs_vol = token.get('cs_volatility_score')
    if cs_vol is not None and cs_vol > 95:
        score *= 0.9

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


    # Layer 10: Zerion
    log.info("Layer 10: Zerion (token + wallet data)...")
    start = time.time()
    try:
        zerion = ZerionEnricher()
        _, count = zerion.enrich_batch(enriched)
        status.record('Zerion', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('Zerion', False, 0, len(enriched), str(e), time.time() - start)

    # Layer 11: CoinStats
    log.info("Layer 11: CoinStats (risk score)...")
    start = time.time()
    try:
        cs = CoinStatsEnricher()
        _, count = cs.enrich_batch(enriched)
        status.record('CoinStats', True, count, len(enriched), elapsed=time.time() - start)
    except Exception as e:
        status.record('CoinStats', False, 0, len(enriched), str(e), time.time() - start)
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
            # Zerion
            'zerion_market_cap': token.get('zerion_market_cap'),
            'zerion_fdv': token.get('zerion_fdv'),
            'zerion_verified': token.get('zerion_verified'),
            'zerion_chain_count': token.get('zerion_chain_count'),
            # CoinStats
            'cs_risk_score': token.get('cs_risk_score'),
            'cs_liquidity_score': token.get('cs_liquidity_score'),
            'cs_volatility_score': token.get('cs_volatility_score'),
            'cs_rank': token.get('cs_rank'),
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
    args = parser.parse_args()

    global MAX_ENRICH, MIN_CHANNEL_COUNT
    if args.max_tokens:
        MAX_ENRICH = args.max_tokens
    if args.min_channels:
        MIN_CHANNEL_COUNT = args.min_channels

    start = time.time()
    result = run_enricher()
    elapsed = time.time() - start
    log.info(f"\nCompleted in {elapsed:.1f}s: {json.dumps(result, default=str)}")
    return 0 if result.get('status') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
