#!/usr/bin/env python3
"""
GMGN enricher - comprehensive token data via gmgn-cli.
DATA ONLY - never for trading.

Unique data not available from other APIs:
  - Dev conviction: creator_token_balance, creator_token_status, dev_team_hold_rate
  - Bot detection: bot_degen_rate, top_rat_trader_percentage, top_bundler_trader_percentage
  - Smart money: smart_wallets count, renowned_wallets, top_wallets
  - Security: renounced_mint, renounced_freeze_account, burn_status, honeypot
  - Social: twitter_username, website, telegram links
  - Holder analytics: holder_count, top_10_holder_rate, fresh_wallet_rate
"""

import os
import json
import subprocess
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')

GMGN_CLI = str(Path.home() / '.hermes' / 'gmgn-cli' / 'dist' / 'index.js')
GMGN_API_KEY = os.getenv('GMGN_API_KEY', '')
GMGN_DELAY = 0.5

CHAIN_MAP = {
    'solana': 'sol', 'sol': 'sol',
    'base': 'base',
    'binance': 'bsc', 'bsc': 'bsc', 'ethereum': 'base', 'eth': 'base',
}


class GMGNEnricher:
    def __init__(self):
        self.last_call = 0
        self.cache = {}

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < GMGN_DELAY:
            time.sleep(GMGN_DELAY - elapsed)
        self.last_call = time.time()

    def _run_cmd(self, args: list) -> Optional[dict]:
        """Run gmgn-cli and parse JSON output."""
        self._rate_limit()
        try:
            env = {**os.environ, 'GMGN_API_KEY': GMGN_API_KEY}
            result = subprocess.run(
                ['node', GMGN_CLI] + args,
                capture_output=True, text=True, timeout=30, env=env
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout.strip())
        except Exception:
            pass
        return None

    def enrich(self, chain: str, address: str) -> Dict[str, Any]:
        cache_key = f"{chain}:{address}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        gmgn_chain = CHAIN_MAP.get(chain.lower())
        if not gmgn_chain:
            return {}

        if not GMGN_API_KEY:
            return {}

        # Get token info + security in parallel (run sequentially for now)
        info = self._run_cmd(['token', 'info', '--chain', gmgn_chain, '--address', address])
        security = self._run_cmd(['token', 'security', '--chain', gmgn_chain, '--address', address])

        if not info and not security:
            return {}

        result = {}

        # From token info
        if info:
            result['gmgn_holder_count'] = info.get('holder_count')
            result['gmgn_liquidity'] = self._float(info.get('liquidity'))
            result['gmgn_price'] = self._float(info.get('price'))
            result['gmgn_ath_price'] = self._float(info.get('ath_price'))
            result['gmgn_total_supply'] = self._float(info.get('total_supply'))
            result['gmgn_launchpad'] = info.get('launchpad', '')
            result['gmgn_creation_ts'] = info.get('creation_timestamp')

            # Dev conviction (KEY DATA)
            dev = info.get('dev', {})
            if dev:
                result['gmgn_creator_address'] = dev.get('creator_address', '')
                result['gmgn_creator_balance'] = self._float(dev.get('creator_token_balance'))
                result['gmgn_creator_status'] = dev.get('creator_token_status', '')
                result['gmgn_dev_hold'] = dev.get('creator_token_status') == 'creator_hold'
                result['gmgn_top_10_holder_rate'] = self._float(dev.get('top_10_holder_rate'))
                result['gmgn_cto_flag'] = dev.get('cto_flag', 0) == 1

                # Twitter history
                tw_count = dev.get('twitter_create_token_count', 0)
                result['gmgn_dev_token_count'] = tw_count
                if tw_count > 5:
                    result['gmgn_dev_token_farmer'] = True

            # Stats (bot/wallet analytics)
            stat = info.get('stat', {})
            if stat:
                result['gmgn_bot_degen_rate'] = self._float(stat.get('bot_degen_rate'))
                result['gmgn_fresh_wallet_rate'] = self._float(stat.get('fresh_wallet_rate'))
                result['gmgn_dev_team_hold_rate'] = self._float(stat.get('dev_team_hold_rate'))
                result['gmgn_private_vault_rate'] = self._float(stat.get('private_vault_hold_rate'))
                result['gmgn_top_entrapment'] = self._float(stat.get('top_entrapment_trader_percentage'))
                result['gmgn_top_bundler'] = self._float(stat.get('top_bundler_trader_percentage'))
                result['gmgn_top_rat'] = self._float(stat.get('top_rat_trader_percentage'))

                # Blue chip owner count
                result['gmgn_bluechip_owners'] = stat.get('bluechip_owner_count', 0)

            # Wallet tags
            tags = info.get('wallet_tags_stat', {})
            if tags:
                result['gmgn_smart_wallets'] = tags.get('smart_wallets', 0)
                result['gmgn_renowned_wallets'] = tags.get('renowned_wallets', 0)
                result['gmgn_sniper_wallets'] = tags.get('sniper_wallets', 0)
                result['gmgn_rat_traders'] = tags.get('rat_trader_wallets', 0)
                result['gmgn_whale_wallets'] = tags.get('whale_wallets', 0)
                result['gmgn_bundler_wallets'] = tags.get('bundler_wallets', 0)

            # Social links
            link = info.get('link', {})
            if link:
                result['gmgn_has_twitter'] = bool(link.get('twitter_username'))
                result['gmgn_has_website'] = bool(link.get('website'))
                result['gmgn_has_telegram'] = bool(link.get('telegram'))
                result['gmgn_twitter_username'] = link.get('twitter_username', '')

        # From security
        if security:
            result['gmgn_renounced_mint'] = security.get('renounced_mint', False)
            result['gmgn_renounced_freeze'] = security.get('renounced_freeze_account', False)
            result['gmgn_burn_status'] = security.get('burn_status', 'unknown')
            result['gmgn_burn_ratio'] = self._float(security.get('burn_ratio'))
            result['gmgn_honeypot'] = security.get('honeypot', 0) == 1
            result['gmgn_buy_tax'] = self._float(security.get('buy_tax'))
            result['gmgn_sell_tax'] = self._float(security.get('sell_tax'))
            result['gmgn_is_locked'] = security.get('lock_summary', {}).get('is_locked', False)

        self.cache[cache_key] = result
        return result

    def enrich_batch(self, tokens: List[dict]) -> List[dict]:
        """Enrich batch - only for supported chains."""
        enriched = []
        for token in tokens:
            chain = token.get('chain', '')
            addr = token.get('contract_address', '')
            gmgn_chain = CHAIN_MAP.get(chain.lower())
            if not gmgn_chain:
                enriched.append(token)
                continue
            data = self.enrich(chain, addr)
            if data:
                enriched.append({**token, **data})
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
    e = GMGNEnricher()
    r = e.enrich('solana', '3TYgKwkE2Y3rxdw9osLRSpxpXmSC1C1oo19W9KHspump')
    for k, v in sorted(r.items()):
        print(f"  {k}: {v}")
