#!/usr/bin/env python3
"""
Derived Security Analyzer - Compute GoPlus/De.Fi equivalent signals
from Dexscreener data and Solana RPC for tokens NOT indexed by those APIs.

Derives:
  1. Effective buy/sell tax (from volume vs price impact)
  2. Volume momentum (acceleration/deceleration)
  3. Liquidity depth risk (liq/FDV ratio, liquidity drain)
  4. Mint authority check (Solana RPC - is token mintable?)
  5. Holder concentration (Solana RPC - getTokenLargestAccounts)
  6. Transaction velocity (txns/time trends)
  7. Social credibility (websites, socials from Dexscreener)
  8. Price rug detection (sudden dumps with low buys)
"""

import os
import time
import json
import requests
import logging
from typing import Dict, Any, Optional, List, Tuple

log = logging.getLogger('derived_security')

# Solana RPC (free tier, rate limited)
SOLANA_RPC = 'https://api.mainnet-beta.solana.com'
RPC_DELAY = 0.5


class DerivedSecurityAnalyzer:
    def __init__(self):
        self.session = requests.Session()
        self.last_rpc = 0

    def _rpc_call(self, method: str, params: list) -> Optional[dict]:
        """Call Solana RPC with rate limiting."""
        elapsed = time.time() - self.last_rpc
        if elapsed < RPC_DELAY:
            time.sleep(RPC_DELAY - elapsed)
        self.last_rpc = time.time()
        try:
            resp = self.session.post(SOLANA_RPC, json={
                'jsonrpc': '2.0', 'id': 1,
                'method': method, 'params': params
            }, timeout=15)
            if resp.status_code == 200:
                return resp.json().get('result')
        except Exception:
            pass
        return None

    def analyze(self, chain: str, address: str, dex_data: dict) -> Dict[str, Any]:
        """
        Derive security signals from available data.
        dex_data: output from DexscreenerEnricher.enrich_token()
        """
        signals = {}

        # ── From Dexscreener data ──

        # 1. Effective tax rate estimation
        tax_signals = self._estimate_tax(dex_data)
        signals.update(tax_signals)

        # 2. Volume momentum
        vol_signals = self._volume_momentum(dex_data)
        signals.update(vol_signals)

        # 3. Liquidity depth risk
        liq_signals = self._liquidity_risk(dex_data)
        signals.update(liq_signals)

        # 4. Transaction velocity
        txn_signals = self._transaction_velocity(dex_data)
        signals.update(txn_signals)

        # 5. Price rug detection
        rug_signals = self._detect_price_rug(dex_data)
        signals.update(rug_signals)

        # 6. Social credibility
        social_signals = self._social_credibility(dex_data)
        signals.update(social_signals)

        # ── From Solana RPC (only for Solana tokens) ──
        if chain.lower() == 'solana':
            rpc_signals = self._solana_onchain_check(address)
            signals.update(rpc_signals)

        return signals

    def _estimate_tax(self, dex: dict) -> dict:
        """
        Estimate effective buy/sell tax from transaction patterns.
        High tax = buys happen but price doesn't move proportionally.
        """
        txns = dex.get('txns_h24', {})
        buys = txns.get('buys', 0) or 0
        sells = txns.get('sells', 0) or 0
        total = buys + sells

        result = {}

        if total > 0:
            buy_ratio = buys / total
            result['derived_buy_ratio'] = round(buy_ratio, 3)

            # Extreme buy/sell asymmetry suggests tax or manipulation
            if buy_ratio > 0.85:
                result['derived_suspect_buy_inflate'] = True
            elif buy_ratio < 0.20:
                result['derived_suspect_sell_pressure'] = True

        # Check h1 vs h6 buy ratio trend
        h1 = dex.get('txns_h1', {})
        h6 = dex.get('txns_h6', {})
        h1_buys = (h1.get('buys', 0) or 0)
        h1_sells = (h1.get('sells', 0) or 0)
        h6_buys = (h6.get('buys', 0) or 0)
        h6_sells = (h6.get('sells', 0) or 0)

        h1_total = h1_buys + h1_sells
        h6_total = h6_buys + h6_sells

        if h1_total > 10 and h6_total > 20:
            h1_buy_ratio = h1_buys / h1_total
            h6_buy_ratio = h6_buys / h6_total
            # If buy ratio is dropping, sentiment is shifting negative
            if h1_buy_ratio < h6_buy_ratio - 0.15:
                result['derived_buy_ratio_declining'] = True

        return result

    def _volume_momentum(self, dex: dict) -> dict:
        """Detect volume acceleration/deceleration."""
        v24 = dex.get('volume_h24', 0) or 0
        v6 = dex.get('volume_h6', 0) or 0
        v1 = dex.get('volume_h1', 0) or 0
        v5 = dex.get('volume_m5', 0) or 0

        result = {}

        if v24 > 0:
            # h6 extrapolated to 24h vs actual 24h
            v6_rate = v6 * 4  # extrapolate to 24h
            if v6_rate < v24 * 0.1:
                result['derived_volume_dying'] = True
            elif v6_rate > v24 * 2:
                result['derived_volume_accelerating'] = True

            # h1 extrapolated vs h6
            if v6 > 0:
                v1_rate = v1 * 6
                if v1_rate < v6 * 0.2:
                    result['derived_recent_slowdown'] = True
                elif v1_rate > v6 * 3:
                    result['derived_recent_spike'] = True

        # No transactions recently
        if v5 == 0 and v1 == 0:
            result['derived_no_recent_activity'] = True

        return result

    def _liquidity_risk(self, dex: dict) -> dict:
        """Assess liquidity depth and rug risk."""
        liq = dex.get('liquidity_usd', 0) or 0
        fdv = dex.get('fdv', 0) or 0

        result = {}

        if fdv > 0:
            liq_ratio = liq / fdv
            result['derived_liq_fdv_ratio'] = round(liq_ratio, 4)

            if liq_ratio < 0.02:
                result['derived_liq_risk'] = 'critical'
            elif liq_ratio < 0.05:
                result['derived_liq_risk'] = 'high'
            elif liq_ratio < 0.10:
                result['derived_liq_risk'] = 'moderate'
            else:
                result['derived_liq_risk'] = 'low'

        if liq == 0:
            result['derived_no_liquidity'] = True

        return result

    def _transaction_velocity(self, dex: dict) -> dict:
        """Measure transaction velocity and trends."""
        txns_h24 = dex.get('txns_h24', {})
        txns_h1 = dex.get('txns_h1', {})
        txns_m5 = dex.get('txns_m5', {})

        total_24h = (txns_h24.get('buys', 0) or 0) + (txns_h24.get('sells', 0) or 0)
        total_1h = (txns_h1.get('buys', 0) or 0) + (txns_h1.get('sells', 0) or 0)
        total_5m = (txns_m5.get('buys', 0) or 0) + (txns_m5.get('sells', 0) or 0)

        result = {'derived_txns_24h': total_24h}

        if total_24h > 0:
            # Transactions per hour average
            tph_avg = total_24h / 24
            result['derived_txns_per_hour_avg'] = round(tph_avg, 1)

            # Is activity increasing or decreasing?
            if total_1h > tph_avg * 2:
                result['derived_activity_hot'] = True
            elif total_1h < tph_avg * 0.2 and total_24h > 20:
                result['derived_activity_cold'] = True

        # Transactions per minute
        if total_5m > 0:
            result['derived_txns_per_min'] = total_5m

        return result

    def _detect_price_rug(self, dex: dict) -> dict:
        """Detect potential rug pull from price/volume patterns."""
        result = {}

        pc_h1 = dex.get('price_change_h1')
        pc_h6 = dex.get('price_change_h6')
        vol_h1 = dex.get('volume_h1', 0) or 0

        # Sudden massive dump
        if pc_h1 is not None and pc_h1 < -50:
            result['derived_massive_dump'] = True

        # Price dumping with volume = active rug
        if pc_h1 is not None and pc_h1 < -30 and vol_h1 > 1000:
            result['derived_possible_rug'] = True

        # Gained then lost (pump and dump pattern)
        if pc_h6 is not None and pc_h1 is not None:
            if pc_h6 > 100 and pc_h1 < -20:
                result['derived_pump_and_dump'] = True

        return result

    def _social_credibility(self, dex: dict) -> dict:
        """Assess social presence as credibility signal."""
        # Dexscreener info is in the pair data, not in our enricher output
        # We'd need to re-check the raw pair data
        # For now, use what we can from the enricher
        result = {}

        age = dex.get('age_hours')
        if age is not None:
            if age < 0.5:
                result['derived_brand_new'] = True  # <30min old
            elif age < 1:
                result['derived_very_new'] = True

        return result

    def _solana_onchain_check(self, address: str) -> dict:
        """Check Solana on-chain data for mint authority and holder info."""
        result = {}

        # 1. Check if mint account exists and has mint authority
        mint_info = self._rpc_call('getAccountInfo', [
            address,
            {'encoding': 'jsonParsed'}
        ])

        if mint_info and mint_info.get('value'):
            parsed = mint_info['value'].get('data', {}).get('parsed', {})
            if parsed.get('type') == 'mint':
                mint_data = parsed.get('info', {})
                mint_authority = mint_data.get('mintAuthority')
                freeze_authority = mint_data.get('freezeAuthority')
                supply = mint_data.get('supply')
                decimals = mint_data.get('decimals')

                result['derived_has_mint_authority'] = mint_authority is not None
                result['derived_has_freeze_authority'] = freeze_authority is not None
                result['derived_mint_risk'] = (
                    'critical' if mint_authority
                    else 'none'
                )

                if supply and decimals:
                    try:
                        ui_supply = int(supply) / (10 ** int(decimals))
                        result['derived_supply'] = ui_supply
                    except:
                        pass

        # 2. Get top holders (largest token accounts)
        largest = self._rpc_call('getTokenLargestAccounts', [address])
        if largest and largest.get('value'):
            accounts = largest['value']
            total_ui = sum(float(a.get('uiAmount', 0) or 0) for a in accounts)
            if total_ui > 0:
                top_3 = sum(float(a.get('uiAmount', 0) or 0) for a in accounts[:3])
                top_10 = sum(float(a.get('uiAmount', 0) or 0) for a in accounts[:10])
                result['derived_top_3_holder_pct'] = round(top_3 / total_ui * 100, 2)
                result['derived_top_10_holder_pct'] = round(top_10 / total_ui * 100, 2)

                # Check if any single holder has >50%
                max_holder_pct = max(
                    float(a.get('uiAmount', 0) or 0) / total_ui
                    for a in accounts
                ) * 100
                result['derived_max_holder_pct'] = round(max_holder_pct, 2)

                if max_holder_pct > 50:
                    result['derived_whale_dominant'] = True

        return result

    def analyze_batch(self, tokens: List[dict]) -> List[dict]:
        """Enrich a batch of tokens with derived security data."""
        enriched = []
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')
            dex = token.get('dex', {})

            derived = self.analyze(chain, addr, dex)
            if derived:
                enriched.append({**token, **derived})
            else:
                enriched.append(token)
        return enriched


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(os.path.dirname(__file__)))
    from dexscreener_enricher import DexscreenerEnricher

    analyzer = DerivedSecurityAnalyzer()
    dex = DexscreenerEnricher()

    # Test with a Solana token
    addr = os.getenv('API_KEY', '')
    dex_data = dex.enrich_token('solana', addr)
    print(f"Dexscreener data: {len(dex_data)} fields")

    derived = analyzer.analyze('solana', addr, dex_data)
    print(f"\nDerived signals:")
    for k, v in sorted(derived.items()):
        print(f"  {k}: {v}")
