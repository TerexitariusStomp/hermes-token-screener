#!/usr/bin/env python3
"""Pattern learning engine for smart-money wallet behaviors."""
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict
from smart_money_config import (
    WALLET_PROFILES_PATH, COMPOSITE_PATTERNS_PATH, DATA_DIR, PATTERN_UPDATE_INTERVAL_HOURS
)

class PatternLearner:
    def __init__(self):
        self.wallet_profiles = self._load_wallet_profiles()
        self.composite_patterns = self._load_composite_patterns()
        self.last_pattern_update = self.composite_patterns.get('generated_at', 0)

    def _load_wallet_profiles(self) -> List[Dict[str, Any]]:
        profiles = []
        if WALLET_PROFILES_PATH.exists():
            try:
                with open(WALLET_PROFILES_PATH, 'r') as f:
                    for line in f:
                        try:
                            profiles.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                print(f"[PatternLearner] Profile load error: {e}")
        return profiles

    def _load_composite_patterns(self) -> Dict[str, Any]:
        if COMPOSITE_PATTERNS_PATH.exists():
            try:
                return json.loads(COMPOSITE_PATTERNS_PATH.read_text())
            except Exception as e:
                print(f"[PatternLearner] Composite load error: {e}")
        return {'generated_at': 0}

    def add_token_analysis(self, token_address: str, smart_wallets: List[Dict[str, Any]], dexscreener_data: Dict[str, Any]):
        """
        For each smart wallet, collect per-token trade stats and append to wallet_profiles.
        """
        chain = dexscreener_data.get('chain')
        fdv = dexscreener_data.get('fdv_usd')
        age_hours = dexscreener_data.get('age_hours')

        for wallet in smart_wallets:
            addr = wallet['address']
            # Construct wallet profile entry for this token
            entry = {
                'wallet': addr,
                'token_address': token_address,
                'chain': chain,
                'realized_pnl': wallet['realized_pnl'],
                'win_rate': wallet['win_rate'],
                'trade_count': wallet['trade_count'],
                'avg_hold_hours': wallet.get('avg_hold_hours'),
                'entry_mcap_estimate': fdv,  # approximate
                'timestamp': time.time(),
                'insider_flag': wallet.get('insider_flag', False),
                'dex': dexscreener_data.get('dex_name')
            }
            with open(WALLET_PROFILES_PATH, 'a') as f:
                f.write(json.dumps(entry) + '\n')
            self.wallet_profiles.append(entry)
        print(f"[PatternLearner] Added {len(smart_wallets)} wallet entries for {token_address[:10]}...")

    def update_composite_patterns(self, force: bool = False):
        """
        Recalculate composite patterns from all wallet profiles.
        Should be called periodically (e.g., hourly) or after enough new data.
        """
        now = time.time()
        if not force and (now - self.last_pattern_update) < (PATTERN_UPDATE_INTERVAL_HOURS * 3600):
            print("[PatternLearner] Skipping pattern update - not enough time elapsed")
            return

        print("[PatternLearner] Updating composite patterns...")
        if not self.wallet_profiles:
            print("[PatternLearner] No wallet profiles to analyze")
            return

        # Group by wallet to compute per-wallet stats
        wallet_groups = defaultdict(list)
        for entry in self.wallet_profiles:
            wallet_groups[entry['wallet']].append(entry)

        # Compute aggregate stats across all wallets
        total_tokens = len(self.wallet_profiles)
        # 1. Entry timing distribution: we need first liquidity vs entry. For now use token age at analysis as proxy
        entry_age_bins = {'0-15min': 0, '15-60min': 0, '1-6h': 0, '6h+': 0}
        # We don't have precise entry timestamps unless we infer from token age and wallet trade logs.
        # For now, we skip this or assume instantaneous.

        # 2. Preferred FDV bands
        fdv_bands = {'<100k': 0, '100k-500k': 0, '500k-1M': 0, '1M-5M': 0, '5M+': 0}
        for entry in self.wallet_profiles:
            fdv = entry.get('entry_mcap_estimate')
            if fdv:
                if fdv < 100_000:
                    fdv_bands['<100k'] += 1
                elif fdv < 500_000:
                    fdv_bands['100k-500k'] += 1
                elif fdv < 1_000_000:
                    fdv_bands['500k-1M'] += 1
                elif fdv < 5_000_000:
                    fdv_bands['1M-5M'] += 1
                else:
                    fdv_bands['5M+'] += 1

        total_fdv_known = sum(fdv_bands.values())
        fdv_distribution = {k: round(v / total_fdv_known * 100, 1) if total_fdv_known else 0 for k, v in fdv_bands.items()}

        # 3. Hold time distribution: winners vs losers
        # Define winner if win_rate > 0.6 and realized_pnl > 0 (PnL is already in USD, positive means winner)
        hold_times_winners = []
        hold_times_losers = []
        for entry in self.wallet_profiles:
            hold = entry.get('avg_hold_hours')
            if hold is None:
                continue
            if entry.get('realized_pnl', 0) > 0:
                hold_times_winners.append(hold)
            else:
                hold_times_losers.append(hold)

        avg_hold_winners = sum(hold_times_winners) / len(hold_times_winners) if hold_times_winners else None
        avg_hold_losers = sum(hold_times_losers) / len(hold_times_losers) if hold_times_losers else None

        # 4. Top chains
        chain_counts = defaultdict(int)
        for entry in self.wallet_profiles:
            chain_counts[entry.get('chain', 'unknown')] += 1
        top_chains = sorted(chain_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_chains_pct = {k: round(v / total_tokens * 100, 1) for k, v in top_chains}

        # 5. Top DEXes
        dex_counts = defaultdict(int)
        for entry in self.wallet_profiles:
            dex = entry.get('dex') or 'unknown'
            dex_counts[dex] += 1
        top_dexes = sorted(dex_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_dexes_pct = {k: round(v / total_tokens * 100, 1) for k, v in top_dexes}

        # 6. Composite score: wallets that have high PnL and win rate; count them
        top_wallets_by_total_pnl = sorted(wallet_groups.items(), key=lambda w: sum(e.get('realized_pnl', 0) for e in w[1]), reverse=True)[:20]
        # We could also derive a "pattern match" threshold later.

        composite = {
            'generated_at': now,
            'num_wallets': len(wallet_groups),
            'num_token_trades': total_tokens,
            'preferred_fdv_distribution': fdv_distribution,
            'avg_hold_hours': {
                'winners': round(avg_hold_winners, 2) if avg_hold_winners else None,
                'losers': round(avg_hold_losers, 2) if avg_hold_losers else None
            },
            'top_chains': top_chains_pct,
            'top_dexes': top_dexes_pct,
            'top_wallets_by_cumulative_pnl': [
                {'wallet': w[0], 'total_pnl': sum(e.get('realized_pnl', 0) for e in w[1])}
                for w in top_wallets_by_total_pnl
            ]
        }

        # Save composite
        try:
            COMPOSITE_PATTERNS_PATH.write_text(json.dumps(composite, indent=2))
            self.composite_patterns = composite
            self.last_pattern_update = now
            print(f"[PatternLearner] Composite patterns updated ({total_tokens} trades, {len(wallet_groups)} wallets)")
        except Exception as e:
            print(f"[PatternLearner] Failed to save composite: {e}")

    def match_token_to_pattern(self, token_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compare a token's attributes against composite pattern to produce a match score.
        """
        fdv = token_analysis.get('dexscreener', {}).get('fdv_usd', 0) or 0
        # Simple scoring: if FDV within preferred bands (e.g., 80% of composite trading volume in bands), high score
        fdv_bands = self.composite_patterns.get('preferred_fdv_distribution', {})
        # Determine band
        if fdv < 100_000:
            band = '<100k'
        elif fdv < 500_000:
            band = '100k-500k'
        elif fdv < 1_000_000:
            band = '500k-1M'
        elif fdv < 5_000_000:
            band = '1M-5M'
        else:
            band = '5M+'

        fdv_match = fdv_bands.get(band, 0)  # percentage of historical volume in this band
        # Normalize to 0-1
        fdv_score = fdv_match / 100

        # Chain match
        chain = token_analysis.get('dexscreener', {}).get('chain', 'unknown')
        chain_match_pct = self.composite_patterns.get('top_chains', {}).get(chain, 0)
        chain_score = chain_match_pct / 100

        # Combination: simple weighted average
        score = round(0.6 * fdv_score + 0.4 * chain_score, 3)

        # Narrative
        if fdv_match >= 60:
            matches = [f"fdv_band_{band}"]
        else:
            matches = []
        if chain_score >= 0.6:
            matches.append(f"prefers_{chain}")

        mismatches = []
        if fdv_match < 30:
            mismatches.append("fdv_outside_comfort_zone")
        if chain_score < 0.3:
            mismatches.append("chain_not_commonly_used")

        return {
            'composite_score': score,
            'matches': matches,
            'mismatches': mismatches,
            'fdv_band': band,
            'fdv_band_volume_pct': fdv_match,
            'chain_volume_pct': chain_match_pct * 100
        }

    def get_wallet_leaderboard(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Rank wallets by cumulative realized PnL (or composite score).
        Returns list of dicts: wallet, total_pnl, num_trades, avg_win_rate, etc.
        """
        if not self.wallet_profiles:
            return []

        wallet_groups = defaultdict(list)
        for entry in self.wallet_profiles:
            wallet_groups[entry['wallet']].append(entry)

        leaderboard = []
        for wallet, entries in wallet_groups.items():
            total_pnl = sum(e.get('realized_pnl', 0) for e in entries)
            avg_win_rate = sum(e.get('win_rate', 0) for e in entries if e.get('win_rate')) / len(entries) if entries else 0
            num_trades = len(entries)
            avg_hold = sum(e.get('avg_hold_hours', 0) for e in entries if e.get('avg_hold_hours')) / len(entries) if entries else 0
            # Composite score based on PnL and win rate
            composite = (total_pnl / 1000) + (avg_win_rate * 100)
            leaderboard.append({
                'wallet': wallet,
                'total_pnl': round(total_pnl, 2),
                'num_trades': num_trades,
                'avg_win_rate': round(avg_win_rate, 3),
                'avg_hold_hours': round(avg_hold, 2),
                'composite_score': round(composite, 2)
            })

        # Sort by total PnL descending
        leaderboard.sort(key=lambda x: x['total_pnl'], reverse=True)
        return leaderboard[:limit]

if __name__ == '__main__':
    learner = PatternLearner()
    # Simulate a token analysis
    token_analysis = {
        'token_address': '0xabc...',
        'dexscreener': {'fdv_usd': 750_000, 'chain': 'base'},
        'smart_wallets': [{'address': '0xw1', 'realized_pnl': 50000, 'win_rate': 0.85, 'trade_count': 12, 'avg_hold_hours': 3.2, 'insider_flag': True}]
    }
    # Normally you'd call add_token_analysis before update
    learner.update_composite_patterns(force=True)
    match = learner.match_token_to_pattern(token_analysis)
    print("Pattern match:", json.dumps(match, indent=2))
