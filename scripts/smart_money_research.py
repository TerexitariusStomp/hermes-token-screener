#!/usr/bin/env python3
"""
Smart-Money Research System: Main orchestrator.

Monitors Telegram call channels, enriches tokens with Dexscreener/GMGN data,
discovers profitable wallets, learns patterns, and outputs actionable insights.

Usage:
  python3 smart_money_research.py              # Run continuous loop
  python3 smart_money_research.py --single <addr> [chain]  # Analyze single token
  python3 smart_money_research.py --learn      # Force pattern update
  python3 smart_money_research.py --test       # Run integrity tests
"""
import os
import sys
import time
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Ensure local imports work when run from cron (any CWD)
sys.path.insert(0, str(Path(__file__).parent))

from smart_money_config import (
    SMART_MONEY_CHANNELS, SMART_MONEY_POLL_INTERVAL, DATA_DIR,
    INSIGHTS_OUTPUT_PATH, LEADERBOARD_OUTPUT_PATH, LOGS_DIR, SMART_MONEY_LOG
)
from telegram_ingestor import TelegramIngestor
from dexscreener_enricher import DexscreenerEnricher
from gmgn_enricher import GMGNEnricher
from wallet_discovery import discover_smart_wallets
from pattern_learner import PatternLearner
from central_db_sink import CentralContractSink

# Setup logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(SMART_MONEY_LOG),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('smart_money')

class SmartMoneyResearch:
    def __init__(self):
        self.ingestor = TelegramIngestor()
        self.dex = DexscreenerEnricher()
        self.gmgn = GMGNEnricher()
        self.learner = PatternLearner()
        self.central_sink = CentralContractSink()
        self.insights: List[Dict[str, Any]] = []
        self._load_insights()

    def _load_insights(self):
        if INSIGHTS_OUTPUT_PATH.exists():
            try:
                with open(INSIGHTS_OUTPUT_PATH, 'r') as f:
                    self.insights = json.load(f)
            except Exception as e:
                log.error(f"Failed to load insights: {e}")
                self.insights = []

    def _save_insights(self):
        try:
            with open(INSIGHTS_OUTPUT_PATH, 'w') as f:
                json.dump(self.insights, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save insights: {e}")

    def _build_contract_records(self, extractions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize Telegram extraction events into central-DB records."""
        records: List[Dict[str, Any]] = []
        seen = set()

        for ext in extractions:
            channel_id = ext.get('channel_id')
            message_id = ext.get('message_id')
            text = ext.get('text', '')
            observed_at = ext.get('timestamp', time.time())

            lower = text.lower()
            chain = 'ethereum'
            if 'base' in lower or '$base' in lower:
                chain = 'base'
            elif 'sol' in lower or 'solana' in lower:
                chain = 'solana'

            for addr_obj in ext.get('token_addresses', []):
                if not isinstance(addr_obj, (tuple, list)) or len(addr_obj) < 2:
                    continue

                original = addr_obj[0]
                normalized = addr_obj[1]
                source = addr_obj[2] if len(addr_obj) > 2 else 'unknown'
                dedupe_key = (message_id, normalized)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                records.append({
                    'channel_id': str(channel_id),
                    'message_id': int(message_id),
                    'chain': chain,
                    'contract_address': normalized,
                    'raw_address': original,
                    'address_source': source,
                    'message_text': text,
                    'observed_at': observed_at,
                    'session_source': 'telegram_user_session',
                })

        return records

    def _generate_narrative(self, token_analysis: Dict[str, Any], smart_wallets: List[Dict[str, Any]]) -> str:
        """Generate human-readable summary."""
        dex = token_analysis.get('dexscreener', {})
        fdv = dex.get('fdv_usd', 0) or 0
        liq = dex.get('liquidity_usd', 0) or 0
        age = dex.get('age_hours')
        pattern = token_analysis.get('pattern_match', {})
        score = pattern.get('composite_score', 0)

        parts = []
        parts.append(f"Token FDV: ${fdv:,.0f}, Liquidity: ${liq:,.0f}")
        if age:
            parts.append(f"Age: {age:.1f}h")
        parts.append(f"Smart wallets found: {len(smart_wallets)}")
        parts.append(f"Pattern match: {score*100:.0f}%")
        if pattern.get('matches'):
            parts.append(f"Matches: {', '.join(pattern['matches'])}")
        if pattern.get('mismatches'):
            parts.append(f"Mismatches: {', '.join(pattern['mismatches'])}")

        return " | ".join(parts)

    def analyze_token(self, chain: str, token_address: str, override_text: str = None) -> Dict[str, Any]:
        """
        Full enrichment pipeline for a single token.
        Returns dict with dexscreener, gmgn, smart_wallets, pattern_match, and narrative.
        """
        log.info(f"Analyzing token {token_address[:10]}... on {chain}")

        # 1. Dexscreener
        dex_data = self.dex.enrich_token(chain, token_address)
        if not dex_data:
            log.warning(f"No Dexscreener data for {token_address}")
            return {}

        # 2. GMGN
        gmgn_data = self.gmgn.enrich_token(chain, token_address)
        if not gmgn_data or not gmgn_data.get('smart_wallets'):
            log.warning(f"No GMGN smart wallets for {token_address}")
            smart_wallets = []
        else:
            # 3. Smart Wallet Discovery
            smart_wallets = discover_smart_wallets(dex_data, gmgn_data)
            gmgn_data['smart_wallets'] = smart_wallets

        # 4. Build token analysis
        token_analysis = {
            'token_address': token_address,
            'chain': chain,
            'dexscreener': dex_data,
            'gmgn': gmgn_data,
            'smart_wallets': smart_wallets,
            'timestamp': time.time()
        }

        # 5. Add to pattern learner
        self.learner.add_token_analysis(token_address, smart_wallets, dex_data)

        # 6. Pattern matching
        match = self.learner.match_token_to_pattern(token_analysis)
        token_analysis['pattern_match'] = match
        token_analysis['narrative'] = self._generate_narrative(token_analysis, smart_wallets)

        return token_analysis

    def run_learning_cycle(self):
        """Update composite patterns and leaderboard."""
        log.info("Running learning cycle...")
        self.learner.update_composite_patterns(force=True)
        leaderboard = self.learner.get_wallet_leaderboard(limit=50)
        try:
            with open(LEADERBOARD_OUTPUT_PATH, 'w') as f:
                json.dump(leaderboard, f, indent=2)
            log.info(f"Wrote leaderboard ({len(leaderboard)} wallets)")
        except Exception as e:
            log.error(f"Failed to write leaderboard: {e}")

    def run_single_pass(self):
        log.info("Running Smart-Money Research single pass...")
        started = self.ingestor.start()
        if not started:
            log.warning("Telegram ingestor failed to start; proceeding with cached data only")

        new_analyses = []
        try:
            if started:
                extractions = self.ingestor.poll_channels()
                log.info(f"Polled Telegram: {len(extractions)} new messages with token addresses")

                records = self._build_contract_records(extractions)
                sent, queued, sink_msg = self.central_sink.send_records(records)
                if records:
                    log.info(
                        f"Central DB export: built={len(records)} sent={sent} queued={queued} status={sink_msg}"
                    )

                for ext in extractions:
                    for addr_obj in ext['token_addresses']:
                        # addr_obj is (original, normalized, source)
                        chain = 'ethereum'
                        text = ext['text'].lower()
                        if 'base' in text or '$base' in text:
                            chain = 'base'
                        elif 'sol' in text or 'solana' in text:
                            chain = 'solana'
                        elif 'eth' in text or 'ethereum' in text:
                            chain = 'ethereum'
                        analysis = self.analyze_token(chain, addr_obj[1])  # normalized address
                        if analysis:
                            new_analyses.append(analysis)

                self.insights.extend(new_analyses)
                self.insights = self.insights[-500:]
                self._save_insights()
            else:
                log.info("No Telegram data; using existing insights for learning")

            # Always run learning cycle
            self.run_learning_cycle()

        finally:
            if started:
                self.ingestor.stop()
            log.info("Smart-Money Research single pass complete")

    def continuous_loop(self):
        """Infinite loop for manual debugging."""
        log.info("Starting Smart-Money Research continuous loop...")
        if not self.ingestor.start():
            log.error("Failed to start Telegram ingestor; exiting")
            return

        last_learn_time = time.time()
        try:
            while True:
                try:
                    extractions = self.ingestor.poll_channels()
                    log.info(f"Polled Telegram: {len(extractions)} new messages with token addresses")

                    records = self._build_contract_records(extractions)
                    sent, queued, sink_msg = self.central_sink.send_records(records)
                    if records:
                        log.info(
                            f"Central DB export: built={len(records)} sent={sent} queued={queued} status={sink_msg}"
                        )

                    new_analyses = []
                    for ext in extractions:
                        for addr_obj in ext['token_addresses']:
                            # addr_obj is (original, normalized, source)
                            chain = 'ethereum'
                            text = ext['text'].lower()
                            if 'base' in text or '$base' in text:
                                chain = 'base'
                            elif 'sol' in text or 'solana' in text:
                                chain = 'solana'
                            elif 'eth' in text or 'ethereum' in text:
                                chain = 'ethereum'
                            analysis = self.analyze_token(chain, addr_obj[1])  # normalized
                            if analysis:
                                new_analyses.append(analysis)

                    self.insights.extend(new_analyses)
                    self.insights = self.insights[-500:]
                    self._save_insights()

                    if time.time() - last_learn_time > (6 * 3600):
                        self.run_learning_cycle()
                        last_learn_time = time.time()

                    time.sleep(SMART_MONEY_POLL_INTERVAL)

                except KeyboardInterrupt:
                    log.info("Interrupted by user")
                    break
                except Exception as e:
                    log.error(f"Loop error: {e}", exc_info=True)
                    time.sleep(SMART_MONEY_POLL_INTERVAL)
        finally:
            self.ingestor.stop()
            log.info("Smart-Money Research stopped")

def main():
    parser = argparse.ArgumentParser(description='Smart-Money Research System')
    parser.add_argument('--single', metavar='ADDRESS', help='Analyze a single token address')
    parser.add_argument('--chain', default='ethereum', help='Chain for --single (default: ethereum)')
    parser.add_argument('--learn', action='store_true', help='Force pattern update and leaderboard generation')
    parser.add_argument('--test', action='store_true', help='Run test mode (connect to Telegram, show channels)')
    parser.add_argument('--daemon', action='store_true', help='Run continuous loop (for manual debugging)')
    args = parser.parse_args()

    try:
        smr = SmartMoneyResearch()

        if args.test:
            if smr.ingestor.start():
                log.info("Telegram connection OK")
                smr.ingestor.stop()
            else:
                log.error("Telegram connection failed")
            return

        if args.learn:
            log.info("Running learning cycle only")
            smr.run_learning_cycle()
            return

        if args.single:
            chain = args.chain
            addr = args.single
            result = smr.analyze_token(chain, addr)
            if result:
                print("\n=== ANALYSIS ===")
                print(json.dumps(result, indent=2))
            else:
                print("Analysis failed (no data).")
            return

        if args.daemon:
            smr.continuous_loop()
        else:
            # Default: single pass (suitable for cron)
            smr.run_single_pass()

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
