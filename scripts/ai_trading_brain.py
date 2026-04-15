"""
AI Trading Brain — Uses Bonsai-8B to make trade decisions on screener tokens.

Connects the token screener pipeline to the trading bot.
When a token scores high enough, the AI decides whether to buy/hold/sell.

Flow:
  1. Load top scored tokens from screener
  2. Filter by trade criteria (min score, FDV range, smart wallets)
  3. Send token data to Bonsai-8B for analysis
  4. AI returns: buy/hold/sell, confidence, position size, stop loss
  5. Execute trades via existing trading_bot.py

Usage:
    python3 ai_trading_brain.py                    # analyze and suggest trades
    python3 ai_trading_brain.py --execute           # execute approved trades
    python3 ai_trading_brain.py --dry-run           # simulate only
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from hermes_screener.config import settings
from hermes_screener.logging import get_logger
from hermes_screener.metrics import metrics

log = get_logger("ai_trading_brain")

TOP_TOKENS_PATH = settings.output_path
TRADE_LOG_PATH = settings.hermes_home / "data" / "token_screener" / "trade_decisions.json"
POSITIONS_PATH = settings.hermes_home / "data" / "token_screener" / "active_positions.json"

# Bonsai-8B endpoint
BONSAI_URL = "http://localhost:8082/v1/chat/completions"
BONSAI_MODEL = "Bonsai-8B.gguf"

# ═══════════════════════════════════════════════════════════════════════════════
# TRADING CRITERIA
# ═══════════════════════════════════════════════════════════════════════════════

MIN_SCORE = 30          # minimum screener score to consider
MIN_SMART_WALLETS = 1   # minimum smart money wallets holding
MAX_FDV = 50_000_000    # max FDV (avoid large caps)
MIN_FDV = 1_000         # min FDV (avoid micro rugs)
MIN_VOLUME = 500        # min 24h volume
MAX_POSITION_PCT = 5.0  # max % of portfolio per trade


# ═══════════════════════════════════════════════════════════════════════════════
# AI DECISION MAKING
# ═══════════════════════════════════════════════════════════════════════════════

def call_bonsai(system: str, prompt: str, max_tokens: int = 150) -> Optional[str]:
    """Call Bonsai-8B for trading analysis."""
    try:
        resp = requests.post(
            BONSAI_URL,
            json={
                "model": BONSAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=45,
        )
        if resp.status_code == 200:
            return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        log.error("bonsai_call_failed", error=str(e))
    return None


def analyze_token_with_ai(token: dict) -> Optional[dict]:
    """
    Send token data to Bonsai-8B for trade decision.

    Returns: {decision, confidence, position_pct, stop_loss_pct, reason}
    """
    system = """You are a crypto trading analyst. Analyze token data and decide whether to buy, hold, or sell.
Consider: score, smart wallet count, FDV, volume, price momentum, social signals, website quality.
Be conservative. Most tokens fail. Only buy with high confidence (>70).

Respond with ONLY a JSON object:
{"decision": "buy|hold|sell", "confidence": 0-100, "position_pct": 0-5, "stop_loss_pct": 5-30, "take_profit_pct": 50-500, "reason": "one sentence"}"""

    prompt = f"""Analyze this token for trading:

Symbol: {token.get('symbol', '?')}
Chain: {token.get('chain', '?')}
Score: {token.get('score', 0)}
Smart Wallets: {token.get('smart_wallet_count', token.get('gmgn_smart_wallets', 0))}
Insiders: {token.get('insider_count', 0)}
FDV: ${token.get('fdv', 0):,.0f}
Volume 24h: ${token.get('volume_h24', 0):,.0f}
Volume 1h: ${token.get('volume_h1', 0):,.0f}
Price 1h: {token.get('price_change_h1', '?')}%
Price 6h: {token.get('price_change_h6', '?')}%
Social Score: {token.get('social_score', 0)}
Website Score: {token.get('website_score', 0)}
Age: {token.get('age_hours', 0):.1f}h
Positives: {', '.join(token.get('positives', []))}
Negatives: {', '.join(token.get('negatives', []))}
Address: {token.get('contract_address', '')}

Current market context: BTC trending, Solana active, memecoin season."""

    response = call_bonsai(system, prompt)
    if not response:
        return None

    # Parse JSON from response
    import re
    json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return {"decision": "hold", "confidence": 0, "reason": "AI response unparseable"}


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE FILTERING
# ═══════════════════════════════════════════════════════════════════════════════

def filter_tradeable_tokens(tokens: List[dict]) -> List[dict]:
    """Filter tokens that meet trading criteria."""
    tradeable = []
    for t in tokens:
        score = t.get("score", 0) or 0
        fdv = t.get("fdv", 0) or 0
        vol = t.get("volume_h24", 0) or 0
        smart = t.get("smart_wallet_count", t.get("gmgn_smart_wallets", 0)) or 0

        if score < MIN_SCORE:
            continue
        if fdv < MIN_FDV or fdv > MAX_FDV:
            continue
        if vol < MIN_VOLUME:
            continue
        if smart < MIN_SMART_WALLETS:
            continue

        # Skip if honeypot
        if t.get("goplus_is_honeypot"):
            continue

        # Skip if high tax
        buy_tax = t.get("goplus_buy_tax", 0) or 0
        sell_tax = t.get("goplus_sell_tax", 0) or 0
        if buy_tax > 0.10 or sell_tax > 0.10:
            continue

        tradeable.append(t)

    log.info("tokens_filtered", total=len(tokens), tradeable=len(tradeable))
    return tradeable


# ═══════════════════════════════════════════════════════════════════════════════
# POSITION MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def load_positions() -> List[dict]:
    """Load current active positions."""
    if POSITIONS_PATH.exists():
        with open(POSITIONS_PATH) as f:
            return json.load(f).get("positions", [])
    return []


def save_positions(positions: List[dict]):
    """Save active positions."""
    POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_PATH, "w") as f:
        json.dump({"positions": positions, "updated_at": time.time()}, f, indent=2, default=str)


def log_decision(decision: dict):
    """Log a trade decision."""
    TRADE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    history = []
    if TRADE_LOG_PATH.exists():
        try:
            history = json.load(open(TRADE_LOG_PATH))
        except Exception:
            pass

    decision["timestamp"] = time.time()
    decision["timestamp_iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    history.append(decision)

    # Keep last 500 decisions
    history = history[-500:]

    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(history, f, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

def execute_trade(token: dict, decision: dict, dry_run: bool = False) -> dict:
    """
    Execute a trade via the existing trading_bot.py.

    Uses the survival trading bot's swap functionality.
    """
    chain = token.get("chain", "").lower()
    addr = token.get("contract_address", "")
    symbol = token.get("symbol", "?")
    action = decision.get("decision", "hold")
    position_pct = decision.get("position_pct", 1.0)

    result = {
        "symbol": symbol,
        "address": addr,
        "chain": chain,
        "action": action,
        "position_pct": position_pct,
        "confidence": decision.get("confidence", 0),
        "dry_run": dry_run,
        "status": "pending",
    }

    if action != "buy":
        result["status"] = "skipped"
        return result

    if dry_run:
        result["status"] = "dry_run"
        log.info("trade_simulated", symbol=symbol, action=action, confidence=decision.get("confidence"))
        return result

    # Execute via trading_bot subprocess
    try:
        # Build swap command
        cmd = [
            sys.executable,
            str(settings.hermes_home / "scripts" / "trading_bot.py"),
            "--chain", chain,
            "--action", "buy",
            "--token", addr,
            "--amount-pct", str(position_pct),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if proc.returncode == 0:
            result["status"] = "executed"
            result["output"] = proc.stdout[-500:] if proc.stdout else ""
            log.info("trade_executed", symbol=symbol, chain=chain, status="ok")
        else:
            result["status"] = "failed"
            result["error"] = proc.stderr[-500:] if proc.stderr else "unknown"
            log.error("trade_failed", symbol=symbol, error=result["error"])

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        log.error("trade_timeout", symbol=symbol)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        log.error("trade_error", symbol=symbol, error=str(e))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def run_trading_brain(
    execute: bool = False,
    dry_run: bool = True,
    max_trades: int = 3,
) -> Dict[str, Any]:
    """Run the AI trading analysis pipeline."""
    start = time.time()

    log.info("=" * 60)
    log.info("AI Trading Brain starting")
    log.info(f"Execute: {execute}, Dry run: {dry_run}")
    log.info("=" * 60)

    # Load top tokens
    if not TOP_TOKENS_PATH.exists():
        log.error("no_top100")
        return {"status": "no_data"}

    with open(TOP_TOKENS_PATH) as f:
        tokens = json.load(f).get("tokens", [])

    log.info("tokens_loaded", count=len(tokens))

    # Filter tradeable
    tradeable = filter_tradeable_tokens(tokens)
    if not tradeable:
        log.info("no_tradeable_tokens")
        return {"status": "no_tradeable", "tokens_analyzed": len(tokens)}

    # Check existing positions
    positions = load_positions()
    active_symbols = {p.get("symbol") for p in positions if p.get("status") == "active"}

    # Analyze with AI
    decisions = []
    buy_signals = 0

    for token in tradeable[:10]:  # analyze top 10
        symbol = token.get("symbol", "?")

        # Skip if already holding
        if symbol in active_symbols:
            log.info("already_holding", symbol=symbol)
            continue

        log.info("analyzing", symbol=symbol, score=token.get("score"),
                 smart=token.get("smart_wallet_count", token.get("gmgn_smart_wallets", 0)))

        decision = analyze_token_with_ai(token)

        if decision:
            decision["symbol"] = symbol
            decision["address"] = token.get("contract_address", "")
            decision["chain"] = token.get("chain", "")
            decision["score"] = token.get("score", 0)
            decision["fdv"] = token.get("fdv", 0)

            log_decision(decision)
            decisions.append(decision)

            if decision.get("decision") == "buy" and decision.get("confidence", 0) >= 70:
                buy_signals += 1

    # Execute buy orders
    executed = []
    if execute and buy_signals > 0:
        buy_decisions = [d for d in decisions if d.get("decision") == "buy" and d.get("confidence", 0) >= 70]
        buy_decisions.sort(key=lambda d: d.get("confidence", 0), reverse=True)

        for decision in buy_decisions[:max_trades]:
            token = next((t for t in tradeable if t.get("contract_address") == decision.get("address")), None)
            if token:
                result = execute_trade(token, decision, dry_run=dry_run)
                executed.append(result)

                if result["status"] == "executed" and not dry_run:
                    positions.append({
                        "symbol": decision["symbol"],
                        "address": decision["address"],
                        "chain": decision["chain"],
                        "entry_price": token.get("fdv"),  # approximate
                        "position_pct": decision.get("position_pct", 1.0),
                        "stop_loss_pct": decision.get("stop_loss_pct", 15),
                        "take_profit_pct": decision.get("take_profit_pct", 100),
                        "status": "active",
                        "entry_time": time.time(),
                        "ai_confidence": decision.get("confidence"),
                        "ai_reason": decision.get("reason"),
                    })

    if executed and not dry_run:
        save_positions(positions)

    elapsed = time.time() - start

    result = {
        "status": "ok",
        "tokens_analyzed": len(tradeable),
        "decisions": len(decisions),
        "buy_signals": buy_signals,
        "executed": len(executed),
        "active_positions": len([p for p in positions if p.get("status") == "active"]),
        "top_decisions": [
            {"symbol": d["symbol"], "decision": d.get("decision"),
             "confidence": d.get("confidence"), "reason": d.get("reason", "")[:80]}
            for d in decisions[:5]
        ],
        "elapsed": round(elapsed, 1),
    }

    log.info("trading_brain_done", **{k: v for k, v in result.items() if k != "top_decisions"})
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI Trading Brain")
    parser.add_argument("--execute", action="store_true", help="Execute approved trades")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Simulate only")
    parser.add_argument("--max-trades", type=int, default=3)
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    result = run_trading_brain(
        execute=args.execute,
        dry_run=args.dry_run,
        max_trades=args.max_trades,
    )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
