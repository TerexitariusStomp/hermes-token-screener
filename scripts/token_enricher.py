#!/usr/bin/env python3
"""
Token Enricher - Unified multi-source enrichment pipeline with resilient try/bypass.

Consolidates all data sources into one self-contained script:
  Layer 0: Dexscreener (core market data)         [REQUIRED - pipeline stops if this fails]
  Layer 2: GoPlus (EVM security)                   [REMOVED]
  Layer 3: RugCheck (Solana security)              [optional]
  Layer 4: Etherscan (contract verification)       [optional]
  Layer 5: De.Fi (security analysis)               [optional]
  Layer 6: Derived (computed signals)              [optional]
  Layer 7: CoinGecko (market data)                 [optional]
  Layer 8: GMGN (smart money + token security)     [optional]
  Layer 9: Social (Telegram DB)                    [optional]
  Layer 12: Mobula (organic ratio)                 [optional]

Design: Each enricher is tried. If it fails, its fields are skipped but the
pipeline continues. Status of each layer is logged and reported in output.

Usage:
  python3 token_enricher.py                     # normal run
  python3 token_enricher.py --max-tokens 50     # limit enrichment
  python3 token_enricher.py --min-channels 3    # higher threshold

Output: ~/.hermes/data/token_screener/top100.json
"""

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Import async enrichment
from hermes_screener.async_enrichment import run_async_enrichment
from hermes_screener.config import settings
from hermes_screener.logging import get_logger
from hermes_screener.metrics import start_metrics_server
from hermes_screener.revised_scoring import revised_score_token
from hermes_screener.training import ExperienceCollector

# ── Config (from centralized settings) ───────────────────────────────────────
DB_PATH = settings.db_path
OUTPUT_PATH = settings.output_path
TOP_N = settings.top_n
MAX_ENRICH = settings.max_enrich
MIN_CHANNEL_COUNT = settings.min_channels

# Scoring weights
W_CHANNEL = settings.w_channel
W_FRESHNESS = settings.w_freshness
W_LOW_FDV = settings.w_low_fdv
W_VOLUME = settings.w_volume
W_TXNS = settings.w_txns
W_MOMENTUM = settings.w_momentum

SELL_RATIO_THRESHOLD = settings.sell_ratio_threshold
STAGNANT_VOLUME_RATIO = settings.stagnant_volume_ratio
NO_ACTIVITY_HOURS = settings.no_activity_hours

# API keys (empty string = layer gracefully skipped)
COINGECKO_API_KEY = settings.coingecko_api_key
ETHERSCAN_API_KEY = settings.etherscan_api_key
DEFI_API_KEY = settings.defi_api_key
RUGCHECK_API_KEY = settings.rugcheck_api_key
GMGN_API_KEY = settings.gmgn_api_key
SURF_API_KEY = settings.surf_api_key
ZERION_API_KEY = settings.zerion_api_key

# ── Logging + Metrics ────────────────────────────────────────────────────────
log = get_logger("token_enricher")
start_metrics_server()
collector = ExperienceCollector(source_script="token_enricher")


# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════


def score_token(token: dict) -> tuple[float, list[str], list[str]]:
    dex = token.get("dex", {})
    score = 0.0
    positives = []
    negatives = []

    # ── SYMBOL BLOCKLIST: fiat/stablecoins are not tradeable tokens ──
    BLOCKED_SYMBOLS = {
        "usd",
        "usdt",
        "usdc",
        "dai",
        "busd",
        "tusd",
        "eur",
        "gbp",
        "jpy",
        "cny",
        "btc",
        "eth",
        "sol",
        "bnb",
        "xrp",
        "wsol",
        "weth",
        "wbtc",
        "steth",
        "cbeth",
        "sui",
        "matic",
    }
    symbol = (dex.get("symbol") or token.get("symbol") or "").lower().strip()
    if symbol in BLOCKED_SYMBOLS:
        return 0, [], [f"BLOCKED: {symbol.upper()} is not a tradeable token"]

    # ── DISQUALIFIERS (return 0 immediately) ──
    if token.get("gmgn_honeypot"):
        return 0, [], ["HONEYPOT"]
    if token.get("goplus_is_honeypot"):
        return 0, [], ["HONEYPOT"]
    if token.get("rugcheck_rugged"):
        return 0, [], ["RUGGED"]
    if token.get("defi_scammed"):
        return 0, [], ["SCAMMED"]
    if token.get("derived_possible_rug"):
        return 0, [], ["POSSIBLE RUG"]
    if token.get("derived_massive_dump"):
        return 0, [], ["MASSIVE DUMP"]

    pc_h1 = dex.get("price_change_h1")
    pc_h6 = dex.get("price_change_h6")
    pc_h24 = dex.get("price_change_h24")
    fdv = dex.get("fdv") or dex.get("market_cap") or 0
    vol_h24 = dex.get("volume_h24", 0) or 0
    vol_h1 = dex.get("volume_h1", 0) or 0
    age_hours = dex.get("age_hours")
    channel_count = token.get("channel_count", 0)
    mentions = token.get("mentions", 0)
    smart = token.get("gmgn_smart_wallets", 0)

    # ── 1. FDV/VOLUME RATIO (0-25) ──
    # Low FDV + high volume = high opportunity
    # ZERO VOLUME = dead token, heavily penalize
    if vol_h24 <= 0:
        # Dead token - no trading activity
        score -= 20
        negatives.append("no volume")
        # Still allow minimal score if very fresh (< 2h) and has FDV
        if fdv > 0 and age_hours is not None and age_hours < 2:
            score += 3
    elif fdv > 0:
        vol_fdv_ratio = vol_h24 / fdv
        if vol_fdv_ratio > 2:
            fdv_vol_score = 25  # FDV $100K, vol $200K+
        elif vol_fdv_ratio > 1:
            fdv_vol_score = 22
        elif vol_fdv_ratio > 0.5:
            fdv_vol_score = 18
        elif vol_fdv_ratio > 0.2:
            fdv_vol_score = 14
        elif vol_fdv_ratio > 0.05:
            fdv_vol_score = 10
        else:
            fdv_vol_score = 5
        score += fdv_vol_score
    elif fdv > 0:
        # FDV but no volume data - minor points only
        if fdv < 50_000:
            score += 5
        elif fdv < 200_000:
            score += 3
        else:
            score += 1

    # ── STALE DATA PENALTY: no price changes = dead ──
    if pc_h1 is None and pc_h6 is None and pc_h24 is None:
        score *= 0.3
        negatives.append("stale data")

    # ── 2. CHANNELS + MENTIONS (0-20) ──
    # More channels mentioning = more legitimate discovery
    if channel_count >= 10:
        score += 12
    elif channel_count >= 5:
        score += 9
    elif channel_count >= 3:
        score += 6
    elif channel_count >= 2:
        score += 3

    if mentions >= 10:
        score += 8
    elif mentions >= 5:
        score += 6
    elif mentions >= 3:
        score += 4
    elif mentions >= 1:
        score += 2

    # ── 3. SMART WALLETS (0-15) ──
    if smart >= 50:
        score += 15
    elif smart >= 30:
        score += 12
    elif smart >= 20:
        score += 10
    elif smart >= 10:
        score += 7
    elif smart >= 5:
        score += 4
    elif smart >= 1:
        score += 2

    # ── 4. DEV HOLDING (0-10) ──
    if token.get("gmgn_dev_hold"):
        score += 10
    dev_rate = token.get("gmgn_dev_team_hold_rate")
    if dev_rate is not None and dev_rate > 0.05:
        score += 3

    # ── 5. SOCIAL SIGNALS (0-10) ──
    tw_sent = token.get("tw_sentiment_score", 0) or 0
    social = token.get("social_score", 0) or 0
    if tw_sent > 70:
        score += 5
    elif tw_sent > 50:
        score += 3
    if social > 20:
        score += 5
    elif social > 10:
        score += 3
    elif social > 5:
        score += 1

    # ── 6. PRICE MOMENTUM (0-10) ──
    # Positive % on ALL timeframes = strong bullish
    all_positive = True
    if pc_h1 is not None:
        if pc_h1 > 0:
            score += 3
        else:
            all_positive = False
    if pc_h6 is not None:
        if pc_h6 > 0:
            score += 3
        else:
            all_positive = False
    if pc_h24 is not None:
        if pc_h24 > 0:
            score += 2
        else:
            all_positive = False
    if all_positive and pc_h1 and pc_h6 and pc_h24:
        score += 2  # bonus for all-positive

    # ── 6.5. MICROSTRUCTURE SCANNER SIGNALS (0-10) ──
    # Derived from live trade-flow heuristics inspired by memecoin scanner workflows.
    scanner = token.get("scanner", {}) or {}
    ew_score = scanner.get("early_warning_score", 0) or 0
    heat_status = scanner.get("heat_status", "") or ""
    whale_cluster = bool(scanner.get("whale_cluster", False))

    if ew_score >= 8:
        score += 5
    elif ew_score >= 6:
        score += 3
    elif ew_score >= 4:
        score += 1

    if heat_status == "hot":
        score += 2
    elif heat_status == "building":
        score += 1
    elif heat_status == "peak":
        score -= 2
        negatives.append("overheated flow")

    if whale_cluster:
        score += 3
        positives.append("whale cluster")

    # ── 7. AGE PENALTY (older = harder to move) ──
    if age_hours is not None:
        if age_hours > 720:
            score *= 0.5  # >30 days
        elif age_hours > 168:
            score *= 0.7  # >7 days
        elif age_hours > 72:
            score *= 0.85  # >3 days

    # ── STEEP DECLINE PENALTIES (>20% loss on any timeframe) ──
    if pc_h1 is not None:
        if pc_h1 < -60:
            score *= 0.1
            negatives.append(f"CRASH h1 ({pc_h1:+.0f}%)")
        elif pc_h1 < -40:
            score *= 0.2
            negatives.append(f"steep decline h1 ({pc_h1:+.0f}%)")
        elif pc_h1 < -20:
            score *= 0.5
            negatives.append(f"decline h1 ({pc_h1:+.0f}%)")

    if pc_h6 is not None:
        if pc_h6 < -70:
            score *= 0.1
            negatives.append(f"DEAD h6 ({pc_h6:+.0f}%)")
        elif pc_h6 < -50:
            score *= 0.2
            negatives.append(f"crashed h6 ({pc_h6:+.0f}%)")
        elif pc_h6 < -20:
            score *= 0.5
            negatives.append(f"declining h6 ({pc_h6:+.0f}%)")

    if pc_h24 is not None:
        if pc_h24 < -80:
            score *= 0.1
            negatives.append(f"DEAD h24 ({pc_h24:+.0f}%)")
        elif pc_h24 < -50:
            score *= 0.3
            negatives.append(f"collapsed h24 ({pc_h24:+.0f}%)")
        elif pc_h24 < -20:
            score *= 0.6
            negatives.append(f"down h24 ({pc_h24:+.0f}%)")

    # Death spiral
    if vol_h24 > 0 and vol_h1 < vol_h24 * 0.005 and pc_h6 is not None and pc_h6 < -10:
        score *= 0.3
        negatives.append("death spiral")

    # ── MULTIPLIERS (positive only) ──
    if token.get("etherscan_verified"):
        score *= 1.15

    if token.get("gmgn_renounced_mint") is True:
        score *= 1.10
    elif token.get("gmgn_renounced_mint") is False:
        score *= 0.3
        negatives.append("mint not renounced")

    if token.get("rugcheck_freeze_renounced") is False:
        score *= 0.5

    # ── BONDING CURVE DETECTION ──
    dex_name = (dex.get("dex") or "").lower()
    liq = dex.get("liquidity_usd") or 0
    on_bonding_curve = False

    # Pump.fun tokens that haven't graduated to PumpSwap
    if dex_name in ("pumpfun", "pump.fun"):
        on_bonding_curve = True
    # Low liquidity + young = likely still on bonding curve
    elif fdv > 0 and liq > 0 and age_hours is not None and age_hours < 24:
        liq_ratio = liq / fdv
        if liq_ratio < 0.02:  # Less than 2% liquidity ratio
            on_bonding_curve = True

    if on_bonding_curve:
        score *= 0.5
        negatives.append("on bonding curve")

    if token.get("rugcheck_freeze_renounced") is False:
        score *= 0.5
        negatives.append("freeze not renounced")

    if token.get("gmgn_burn_status") == "burn":
        score *= 1.15
        if "burned" not in str(positives).lower():
            positives.append("burned")

    if token.get("gmgn_cto_flag"):
        score *= 1.10
        positives.append("CTO")

    if token.get("gmgn_dev_token_farmer"):
        score *= 0.6
        negatives.append("token farmer")

    if token.get("derived_has_mint_authority"):
        score *= 0.3
        negatives.append("HAS MINT AUTHORITY")
    if token.get("derived_has_freeze_authority"):
        score *= 0.5

    # CoinGecko listings (unique signals)
    if token.get("cg_is_listed"):
        score *= 1.08
        positives.append("CoinGecko listed")
    if token.get("cg_listed_on_binance"):
        score *= 1.10
        positives.append("BINANCE")
    elif token.get("cg_listed_on_coinbase"):
        score *= 1.08
        positives.append("COINBASE")

    # Volume penalties
    buys_h1 = (dex.get("txns_h1", {}) or {}).get("buys", 0) or 0
    sells_h1 = (dex.get("txns_h1", {}) or {}).get("sells", 0) or 0
    if sells_h1 > 0 and buys_h1 == 0:
        score *= 0.1
        negatives.append("ONLY SELLS")
    elif sells_h1 > 0:
        sell_ratio = sells_h1 / (buys_h1 + sells_h1)
        if sell_ratio > SELL_RATIO_THRESHOLD:
            score *= 0.3
            negatives.append(f"HEAVY SELLS ({sell_ratio:.0%})")

    if vol_h24 > 0 and vol_h1 > 0 and vol_h1 < vol_h24 * STAGNANT_VOLUME_RATIO:
        score *= 0.5
        negatives.append("stagnant volume")

    buys_h6 = (dex.get("txns_h6", {}) or {}).get("buys", 0) or 0
    sells_h6 = (dex.get("txns_h6", {}) or {}).get("sells", 0) or 0
    total_h6 = buys_h6 + sells_h6
    if total_h6 == 0 and age_hours and age_hours > 1:
        score *= 0.4
        negatives.append("no txns in 6h")

    # RugCheck
    rc_score = token.get("rugcheck_score", 0)
    if rc_score > 10:
        score *= 0.2
    elif rc_score > 5:
        score *= 0.5

    return round(score, 2), positives, negatives


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════


def get_candidates() -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT chain, contract_address, channel_count, channels_seen,
               mentions, first_seen_at, last_seen_at
        FROM telegram_contracts_unique
        WHERE channel_count >= ?
        ORDER BY channel_count DESC, last_seen_at DESC
        LIMIT ?
    """,
        (MIN_CHANNEL_COUNT, MAX_ENRICH),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    log.info(f"Loaded {len(rows)} candidates (min {MIN_CHANNEL_COUNT} channels)")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# ENRICHER RESULT TRACKING
# ══════════════════════════════════════════════════════════════════════════════


class EnricherResult:
    """Track enrichment pipeline results."""

    def __init__(self):
        self.layers = {}
        self.start_time = time.time()

    def record(
        self,
        layer_name: str,
        success: bool,
        enriched: int,
        total: int,
        error: str = None,
        elapsed: float = 0.0,
    ):
        """Record result for a layer."""
        self.layers[layer_name] = {
            "success": success,
            "enriched": enriched,
            "total": total,
            "error": error,
            "elapsed": elapsed,
        }

    def summary(self) -> list[str]:
        """Generate summary lines."""
        lines = []
        total_elapsed = time.time() - self.start_time
        lines.append(f"Total time: {total_elapsed:.1f}s")
        lines.append(f"Layers: {len(self.layers)}")

        success_count = sum(1 for l in self.layers.values() if l["success"])
        lines.append(f"Successful: {success_count}/{len(self.layers)}")

        for name, result in self.layers.items():
            status = "✅" if result["success"] else "❌"
            lines.append(f"  {status} {name}: {result['enriched']}/{result['total']} ({result['elapsed']:.1f}s)")
            if result["error"]:
                lines.append(f"    Error: {result['error']}")

        return lines


class SocialSignalEnricher:
    """Social signal enrichment for tokens using existing Telegram data."""

    def enrich_batch(self, tokens: list[dict]) -> tuple[int, int]:
        """
        Enrich tokens with social signals from existing data.

        Returns: (enriched_count, total_count)
        """
        enriched_count = 0

        for token in tokens:
            try:
                # Extract social signals from existing data
                signals = self._extract_social_signals(token)
                if signals:
                    token.update(signals)
                    enriched_count += 1
            except Exception as e:
                # Log error but continue with other tokens
                log.debug(f"Social enrichment failed for {token.get('symbol', '?')}: {e}")
                continue

        return enriched_count, len(tokens)

    def _extract_social_signals(self, token: dict) -> dict:
        """Extract social signals from token data."""
        signals = {}

        # Telegram signals (from existing data)
        channel_count = token.get("channel_count", 0) or 0
        mentions = token.get("mentions", 0) or 0

        if channel_count > 0 or mentions > 0:
            # Calculate social score based on Telegram activity
            social_score = min(100, (channel_count * 10) + (mentions * 2))
            signals["social_score"] = social_score

            # Calculate mention velocity if we have timing data
            first_seen = token.get("first_seen_at")
            last_seen = token.get("last_seen_at")
            if first_seen and last_seen and mentions > 0:
                try:
                    hours_active = (last_seen - first_seen) / 3600
                    if hours_active > 0:
                        velocity = mentions / hours_active
                        signals["mention_velocity"] = round(velocity, 2)
                except Exception:
                    pass

            # Determine social quality
            if channel_count >= 5 and mentions >= 20:
                signals["social_quality"] = "high"
            elif channel_count >= 3 and mentions >= 10:
                signals["social_quality"] = "medium"
            else:
                signals["social_quality"] = "low"

        # Twitter signals (if available from enrichment)
        tw_mention_count = token.get("tw_mention_count", 0) or 0
        tw_sentiment_score = token.get("tw_sentiment_score", 0) or 0

        if tw_mention_count > 0:
            signals["twitter_activity"] = tw_mention_count
            signals["twitter_sentiment"] = tw_sentiment_score

        # Combined social momentum
        if signals:
            # Calculate overall social momentum
            telegram_score = signals.get("social_score", 0)
            twitter_score = signals.get("twitter_activity", 0) * 0.5  # Weight Twitter less

            total_momentum = telegram_score + twitter_score
            if total_momentum >= 100:
                signals["social_momentum"] = "very_high"
            elif total_momentum >= 50:
                signals["social_momentum"] = "high"
            elif total_momentum >= 20:
                signals["social_momentum"] = "medium"
            else:
                signals["social_momentum"] = "low"

        return signals


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
        return {"status": "empty", "candidates": 0}

    # Use async enrichment for all layers
    log.info("Starting async enrichment pipeline...")
    start_time = time.time()

    try:
        # Run async enrichment
        enriched, layer_results = asyncio.run(run_async_enrichment(candidates[:MAX_ENRICH], max_enrich=MAX_ENRICH))

        # Record results from async enrichment
        for result in layer_results:
            status.record(
                result.name,
                result.success,
                result.enriched_count,
                result.total_count,
                result.error,
                result.elapsed,
            )

        elapsed = time.time() - start_time
        log.info(f"Async enrichment completed in {elapsed:.1f}s")

    except Exception as e:
        log.error(f"Async enrichment failed: {e}")
        return {"status": "async_failed", "error": str(e)}

    if not enriched:
        log.error("Enrichment returned 0 results")
        return {"status": "no_enrichment", "candidates": len(candidates)}

    # Score tokens
    log.info("Scoring tokens...")
    for token in enriched:
        try:
            collector.record_token_enriched(token)
        except Exception:
            pass
        score, positives, negatives = revised_score_token(token)
        token["score"] = score
        token["positives"] = positives
        token["negatives"] = negatives
        try:
            collector.record_token_scored(token, score, {"positives": positives, "negatives": negatives})
        except Exception:
            pass

    # Filter duplicate token names per chain - keep only top-scoring one per (name, chain)
    def filter_duplicate_names(tokens: list[dict]) -> list[dict]:
        """Filter duplicate token names per chain, keeping only the highest-scoring one."""
        from collections import defaultdict

        # Group tokens by (symbol, chain)
        groups = defaultdict(list)
        for token in tokens:
            symbol = (token.get("symbol") or token.get("dex", {}).get("symbol") or "").upper().strip()
            chain = token.get("chain", "").lower()
            if symbol and chain:
                groups[(symbol, chain)].append(token)

        # Keep only the highest-scoring token per group
        filtered_tokens = []
        for (symbol, chain), group_tokens in groups.items():
            if len(group_tokens) == 1:
                filtered_tokens.append(group_tokens[0])
            else:
                # Sort by score (descending) and keep the top one
                group_tokens.sort(key=lambda t: t.get("score", 0), reverse=True)
                top_token = group_tokens[0]
                filtered_tokens.append(top_token)

                # Log the filtering
                duplicates = group_tokens[1:]
                if duplicates:
                    log.info(
                        "filtered_duplicate_names",
                        symbol=symbol,
                        chain=chain,
                        kept_score=top_token.get("score", 0),
                        filtered_count=len(duplicates),
                        filtered_scores=[t.get("score", 0) for t in duplicates],
                    )

        return filtered_tokens

    # Apply duplicate name filtering before final sorting
    enriched = filter_duplicate_names(enriched)

    # Sort by score
    enriched.sort(key=lambda t: t.get("score", 0), reverse=True)
    top = enriched[:TOP_N]

    # Save output
    output = {
        "status": "ok",
        "generated_at": datetime.utcnow().isoformat(),
        "total_candidates": len(candidates),
        "enriched": len(enriched),
        "top_n": len(top),
        "pipeline_status": status.layers,
        "tokens": top,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    # Save as Phase 1 (initial enrichment scores)
    phase1_path = Path.home() / ".hermes" / "data" / "token_screener" / "top100_phase1_initial.json"
    with open(phase1_path, "w") as f:
        json.dump({**output, "phase": "phase1_initial"}, f, indent=2, default=str)

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
        fdv_val = t.get("fdv") or 0
        vol_val = t.get("volume_h24") or 0
        neg = " | " + ", ".join(t["negatives"][:2]) if t["negatives"] else ""
        log.info(
            f"{i:2}. {t.get('symbol', '?'):12} "
            f"score={t.get('score', 0):6.1f} "
            f"fdv=${fdv_val:>12,.0f} "
            f"vol=${vol_val:>12,.0f} "
            f"age={t.get('age_hours', 0):5.1f}h"
            f"{neg}"
        )

    log.info("")
    elapsed_total = time.time() - status.start_time
    log.info(f"Completed in {elapsed_total:.1f}s: {json.dumps(output, default=str)}")

    return output


def main():

    parser = argparse.ArgumentParser(description="Token enrichment pipeline")
    parser.add_argument("--max-tokens", type=int, default=None, help="Max tokens to enrich")
    parser.add_argument("--min-channels", type=int, default=None, help="Min channel count")
    parser.add_argument(
        "--async-mode",
        action="store_true",
        dest="async_mode",
        help="Run enrichment layers in parallel (async)",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Force sequential enrichment (original behavior)",
    )
    args = parser.parse_args()

    global MAX_ENRICH, MIN_CHANNEL_COUNT
    if args.max_tokens:
        MAX_ENRICH = args.max_tokens
    if args.min_channels:
        MIN_CHANNEL_COUNT = args.min_channels

    start = time.time()

    if args.async_mode and not args.sequential:
        # Async parallel enrichment
        from hermes_screener.async_enrichment import run_async_enrichment_sync

        candidates = get_candidates()
        if not candidates:
            log.warning("No candidates found")
            return 1
        enriched, layer_results = run_async_enrichment_sync(candidates, MAX_ENRICH)
        if enriched:
            scored = enriched
            elapsed = time.time() - start
            log.info(f"\nAsync completed in {elapsed:.1f}s: {len(enriched)} tokens enriched, " f"{len(scored)} scored")
            result = {"status": "ok", "tokens": len(enriched), "scored": len(scored)}
        else:
            result = {"status": "no_enrichment"}
    else:
        # Sequential enrichment (original)
        result = run_enricher()

    elapsed = time.time() - start
    log.info(f"\nCompleted in {elapsed:.1f}s: {json.dumps(result, default=str)}")
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
