#!/usr/bin/env python3
"""
Trade Monitor — Minute-by-minute AI trade management.

Monitors active positions, detects decay, and decides when to sell/rotate.

Every run:
  1. Load active positions
  2. Fetch current price/volume/holders for each
  3. Detect decay (volume declining, holders leaving, transactions dropping)
  4. Ask Bonsai-8B: hold, sell, or rotate?
  5. Execute decisions via trading_bot.py
  6. Log all actions

Usage:
    python3 trade_monitor.py                     # monitor + suggest (dry run)
    python3 trade_monitor.py --execute            # execute sell orders
    python3 trade_monitor.py --check-decay        # decay analysis only
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
# TOR proxy - route all external HTTP through SOCKS5
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-token-screener"))
import hermes_screener.tor_config

from hermes_screener.config import settings
from hermes_screener.logging import get_logger

log = get_logger("trade_monitor")

POSITIONS_PATH = (
    Path.home() / ".hermes" / "data" / "token_screener" / "active_positions.json"
)
DECISION_LOG = (
    Path.home() / ".hermes" / "data" / "token_screener" / "trade_monitor_log.json"
)
MARKET_HISTORY = (
    Path.home() / ".hermes" / "data" / "token_screener" / "market_history.json"
)
TOP_TOKENS_PATH = settings.output_path

BONSAI_URL = "http://localhost:8082/v1/chat/completions"
BONSAI_MODEL = "Bonsai-8B.gguf"

# Decay thresholds
VOLUME_DECAY_PCT = 30  # volume drop > 30% = decay
HOLDER_DECAY_PCT = 20  # holder count drop > 20% = decay
TX_DECAY_PCT = 40  # transaction count drop > 40% = decay
PRICE_DECAY_PCT = 25  # price drop > 25% from peak = decay
STAGNANT_HOURS = 6  # no price movement for 6h = stagnant


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════


def load_positions() -> List[dict]:
    if POSITIONS_PATH.exists():
        with open(POSITIONS_PATH) as f:
            return json.load(f).get("positions", [])
    return []


def save_positions(positions: List[dict]):
    POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_PATH, "w") as f:
        json.dump(
            {"positions": positions, "updated_at": time.time()},
            f,
            indent=2,
            default=str,
        )


def load_market_history() -> Dict[str, list]:
    if MARKET_HISTORY.exists():
        with open(MARKET_HISTORY) as f:
            return json.load(f)
    return {}


def save_market_history(history: Dict[str, list]):
    MARKET_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    # Keep last 1000 entries per token
    for key in history:
        history[key] = history[key][-1000:]
    with open(MARKET_HISTORY, "w") as f:
        json.dump(history, f, indent=2, default=str)


def log_monitor_decision(decision: dict):
    DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if DECISION_LOG.exists():
        try:
            history = json.load(open(DECISION_LOG))
        except Exception:
            pass
    decision["timestamp"] = time.time()
    decision["timestamp_iso"] = datetime.fromtimestamp(
        time.time(), tz=timezone.utc
    ).isoformat()
    history.append(decision)
    history = history[-500:]
    with open(DECISION_LOG, "w") as f:
        json.dump(history, f, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════


def fetch_token_market_data(address: str, chain: str) -> Optional[dict]:
    """Fetch current market data from Dexscreener."""
    try:
        resp = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{address}",
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        pairs = resp.json().get("pairs", [])
        if not pairs:
            return None

        best = max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
        txns = best.get("txns", {})
        volume = best.get("volume", {})

        return {
            "price_usd": float(best.get("priceUsd", 0) or 0),
            "fdv": best.get("fdv", 0) or 0,
            "liquidity": best.get("liquidity", {}).get("usd", 0) or 0,
            "volume_h24": volume.get("h24", 0) or 0,
            "volume_h1": volume.get("h1", 0) or 0,
            "volume_m5": volume.get("m5", 0) or 0,
            "txns_h24_buys": txns.get("h24", {}).get("buys", 0) or 0,
            "txns_h24_sells": txns.get("h24", {}).get("sells", 0) or 0,
            "txns_h1_buys": txns.get("h1", {}).get("buys", 0) or 0,
            "txns_h1_sells": txns.get("h1", {}).get("sells", 0) or 0,
            "price_change_m5": best.get("priceChange", {}).get("m5"),
            "price_change_h1": best.get("priceChange", {}).get("h1"),
            "price_change_h6": best.get("priceChange", {}).get("h6"),
            "price_change_h24": best.get("priceChange", {}).get("h24"),
            "timestamp": time.time(),
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# DECAY DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


def detect_decay(symbol: str, current: dict, history: list) -> Dict[str, Any]:
    """
    Detect if a token is decaying.

    Decay signals:
      - Volume declining over multiple periods
      - Transaction count dropping
      - Price consistently declining
      - Stagnant (no movement for extended period)
    """
    if len(history) < 3:
        return {"decaying": False, "signals": [], "severity": 0}

    signals = []
    severity = 0

    # Volume decay: compare last 3 data points
    recent_vols = [
        h.get("volume_h1", 0) for h in history[-3:] if h.get("volume_h1", 0) > 0
    ]
    if len(recent_vols) >= 2:
        vol_change = ((recent_vols[-1] - recent_vols[0]) / max(recent_vols[0], 1)) * 100
        if vol_change < -VOLUME_DECAY_PCT:
            signals.append(f"volume_declining ({vol_change:.0f}%)")
            severity += 2

    # Transaction decay: compare buys + sells
    recent_txns = [
        h.get("txns_h1_buys", 0) + h.get("txns_h1_sells", 0) for h in history[-3:]
    ]
    if len(recent_txns) >= 2 and recent_txns[0] > 0:
        tx_change = ((recent_txns[-1] - recent_txns[0]) / recent_txns[0]) * 100
        if tx_change < -TX_DECAY_PCT:
            signals.append(f"transactions_declining ({tx_change:.0f}%)")
            severity += 2

    # Price decay: from peak in history
    prices = [h.get("price_usd", 0) for h in history if h.get("price_usd", 0) > 0]
    if prices:
        peak = max(prices)
        current_price = current.get("price_usd", 0)
        if peak > 0 and current_price > 0:
            drawdown = ((current_price - peak) / peak) * 100
            if drawdown < -PRICE_DECAY_PCT:
                signals.append(f"price_drawdown ({drawdown:.0f}% from peak)")
                severity += 3

    # Stagnant: no significant price movement
    recent_prices = [
        h.get("price_usd", 0) for h in history[-12:] if h.get("price_usd", 0) > 0
    ]
    if len(recent_prices) >= 6:
        price_range = (max(recent_prices) - min(recent_prices)) / max(
            min(recent_prices), 1e-12
        )
        if price_range < 0.02:  # less than 2% movement
            signals.append("stagnant (no movement for extended period)")
            severity += 1

    # Sell pressure: more sells than buys
    buys = current.get("txns_h1_buys", 0)
    sells = current.get("txns_h1_sells", 0)
    if sells > 0 and buys > 0:
        sell_ratio = sells / (buys + sells)
        if sell_ratio > 0.65:
            signals.append(f"sell_pressure ({sell_ratio:.0%} sells)")
            severity += 2

    return {
        "decaying": len(signals) > 0,
        "signals": signals,
        "severity": min(severity, 10),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# AI DECISION MAKING
# ═══════════════════════════════════════════════════════════════════════════════


def call_bonsai(system: str, prompt: str, max_tokens: int = 120) -> Optional[str]:
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
            timeout=30,
        )
        if resp.status_code == 200:
            return (
                resp.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
    except Exception:
        pass
    return None


def ask_ai_position(
    position: dict,
    market: dict,
    decay: dict,
    entry_price: float,
) -> dict:
    """Ask Bonsai-8B what to do with this position."""
    system = """You manage a crypto trading position. Decide: hold, sell, or rotate to a new token.
Be decisive. If decay signals are present, lean toward selling. If profit is large (>100%), consider taking profit.

Respond with ONLY JSON:
{"action": "hold|sell|rotate", "confidence": 0-100, "reason": "one sentence"}"""

    current_price = market.get("price_usd", 0)
    pnl_pct = (
        ((current_price - entry_price) / max(entry_price, 1e-12)) * 100
        if entry_price > 0
        else 0
    )

    prompt = f"""Position: {position.get('symbol', '?')} on {position.get('chain', '?')}
Entry price: ${entry_price:.8f}
Current price: ${current_price:.8f}
PnL: {'+' if pnl_pct > 0 else ''}{pnl_pct:.1f}%
Hold time: {((time.time() - position.get('entry_time', time.time())) / 3600):.1f}h

Current market:
  Volume 1h: ${market.get('volume_h1', 0):,.0f}
  Volume 24h: ${market.get('volume_h24', 0):,.0f}
  Txns 1h: {market.get('txns_h1_buys', 0)} buys, {market.get('txns_h1_sells', 0)} sells
  Price 1h: {market.get('price_change_h1', '?')}%
  Price 6h: {market.get('price_change_h6', '?')}%
  Liquidity: ${market.get('liquidity', 0):,.0f}

Decay analysis:
  Decaying: {decay.get('decaying', False)}
  Severity: {decay.get('severity', 0)}/10
  Signals: {', '.join(decay.get('signals', [])) or 'none'}

Stop loss: {position.get('stop_loss_pct', 15)}%
Take profit: {position.get('take_profit_pct', 100)}%"""

    response = call_bonsai(system, prompt)
    if not response:
        return {"action": "hold", "confidence": 0, "reason": "AI unavailable"}

    import re

    match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {"action": "hold", "confidence": 0, "reason": "parse failed"}


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════


def execute_sell(position: dict, dry_run: bool = True) -> dict:
    """Execute a sell order."""
    chain = position.get("chain", "")
    addr = position.get("address", "")
    symbol = position.get("symbol", "?")

    result = {"symbol": symbol, "action": "sell", "chain": chain, "dry_run": dry_run}

    if dry_run:
        result["status"] = "dry_run"
        log.info("sell_simulated", symbol=symbol)
        return result

    try:
        cmd = [
            sys.executable,
            str(Path.home() / ".hermes" / "scripts" / "trading_bot.py"),
            "--chain",
            chain,
            "--action",
            "sell",
            "--token",
            addr,
            "--amount-pct",
            "100",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        result["status"] = "executed" if proc.returncode == 0 else "failed"
        result["output"] = (proc.stdout or proc.stderr or "")[-300:]
        log.info(
            "sell_executed" if proc.returncode == 0 else "sell_failed",
            symbol=symbol,
            chain=chain,
        )
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        log.error("sell_error", symbol=symbol, error=str(e))

    return result


def find_rotation_candidate(current_symbol: str) -> Optional[dict]:
    """Find a new token to rotate into."""
    if not TOP_TOKENS_PATH.exists():
        return None

    with open(TOP_TOKENS_PATH) as f:
        tokens = json.load(f).get("tokens", [])

    # Find best token that isn't current position
    for t in tokens:
        if t.get("symbol") == current_symbol:
            continue
        score = t.get("score", 0) or 0
        fdv = t.get("fdv", 0) or 0
        if score >= 50 and fdv > 5000:
            return t

    return None


def evaluate_reentry(position: dict, market: dict, decay: dict) -> Optional[dict]:
    """
    After a take-profit exit, evaluate whether to re-enter the token.

    Considers:
      - Price pullback from exit (better entry?)
      - Volume still alive (not dead after the pump)
      - No new decay signals
      - AI recommendation
    """
    exit_price = position.get("_tp_exit_price", 0)
    exit_time = position.get("_tp_exit_time", 0)
    current_price = market.get("price_usd", 0)

    if not exit_price or not current_price or exit_price <= 0:
        return None

    pullback_pct = ((exit_price - current_price) / exit_price) * 100
    hours_since_exit = (time.time() - exit_time) / 3600 if exit_time else 0

    # Don't re-enter too quickly (let it cool)
    if hours_since_exit < 0.5:
        return {
            "reenter": False,
            "reason": f"too soon ({hours_since_exit:.1f}h), let it cool",
        }

    # Don't re-enter if barely pulled back (chasing)
    if pullback_pct < 10:
        return {
            "reenter": False,
            "reason": f"only {pullback_pct:.0f}% pullback, not a good re-entry price",
        }

    # Don't re-enter if decaying badly
    if decay.get("severity", 0) >= 5:
        return {
            "reenter": False,
            "reason": f"decay severity {decay['severity']}/10, token dying",
        }

    # Volume check: is it still alive?
    vol_h1 = market.get("volume_h1", 0)
    if vol_h1 < 500:
        return {"reenter": False, "reason": f"volume dead (${vol_h1:.0f}/h)"}

    # Ask AI
    system = (
        "You are deciding whether to RE-ENTER a token you previously took profit on. "
        "The token pumped, you sold at the peak, and now it has pulled back. "
        "Is this a good re-entry point? "
        'Respond with ONLY JSON: {"reenter": true|false, "confidence": 0-100, "reason": "one sentence"}'
    )

    prompt = (
        f"Token: {position.get('symbol', '?')}\n"
        f"You sold at: ${exit_price:.8f} (take profit)\n"
        f"Current price: ${current_price:.8f}\n"
        f"Pullback: {pullback_pct:.1f}% from your exit\n"
        f"Time since exit: {hours_since_exit:.1f}h\n"
        f"Volume 1h: ${market.get('volume_h1', 0):,.0f}\n"
        f"Txns 1h: {market.get('txns_h1_buys', 0)} buys, {market.get('txns_h1_sells', 0)} sells\n"
        f"Price 1h: {market.get('price_change_h1', '?')}%\n"
        f"Liquidity: ${market.get('liquidity', 0):,.0f}\n"
        f"Decay severity: {decay.get('severity', 0)}/10\n"
        f"Should you re-enter at this lower price?"
    )

    response = call_bonsai(system, prompt)
    if not response:
        return None

    import re

    match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN MONITOR
# ═══════════════════════════════════════════════════════════════════════════════


def run_trade_monitor(execute: bool = False, dry_run: bool = True) -> Dict[str, Any]:
    """Run the trade monitoring loop."""
    start = time.time()

    positions = load_positions()
    active = [p for p in positions if p.get("status") == "active"]

    if not active:
        return {"status": "no_positions", "active": 0}

    history = load_market_history()
    decisions = []
    sells_executed = 0

    for position in active:
        symbol = position.get("symbol", "?")
        addr = position.get("address", "")
        chain = position.get("chain", "")
        entry_price = position.get("entry_price", 0)
        stop_loss = position.get("stop_loss_pct", 15)
        take_profit = position.get("take_profit_pct", 100)

        # Fetch current market data
        market = fetch_token_market_data(addr, chain)
        if not market:
            log.warning("no_market_data", symbol=symbol)
            continue

        # Update market history
        if symbol not in history:
            history[symbol] = []
        history[symbol].append(market)

        # Detect decay
        decay = detect_decay(symbol, market, history[symbol])

        # Check stop loss / take profit
        current_price = market.get("price_usd", 0)
        pnl_pct = (
            ((current_price - entry_price) / max(entry_price, 1e-12)) * 100
            if entry_price > 0
            else 0
        )

        forced_action = None
        if pnl_pct <= -stop_loss:
            forced_action = "sell"
            reason = f"STOP LOSS hit ({pnl_pct:.1f}%)"
        elif pnl_pct >= take_profit:
            forced_action = "sell"
            reason = f"TAKE PROFIT hit ({pnl_pct:.1f}%) — will evaluate re-entry"
            position["_take_profit_exit"] = True
            position["_tp_exit_price"] = current_price
            position["_tp_exit_time"] = time.time()

        # Ask AI (unless stop loss/take profit forced)
        if forced_action:
            decision = {"action": forced_action, "confidence": 95, "reason": reason}
        else:
            decision = ask_ai_position(position, market, decay, entry_price)

        decision["symbol"] = symbol
        decision["pnl_pct"] = round(pnl_pct, 1)
        decision["price"] = current_price
        decision["decay_severity"] = decay.get("severity", 0)
        decision["decay_signals"] = decay.get("signals", [])
        log_monitor_decision(decision)

        action = decision.get("action", "hold")
        confidence = decision.get("confidence", 0)

        log.info(
            "position_evaluated",
            symbol=symbol,
            action=action,
            confidence=confidence,
            pnl=f"{pnl_pct:.1f}%",
            decay=decay.get("severity", 0),
        )

        # Execute if confident
        if action == "sell" and (confidence >= 70 or forced_action):
            if execute or forced_action == "sell":
                sell_result = execute_sell(
                    position, dry_run=dry_run and not forced_action
                )
                decisions.append(
                    {"symbol": symbol, "action": "sell", "result": sell_result}
                )

                if sell_result["status"] == "executed" or (
                    sell_result["status"] == "dry_run" and forced_action
                ):
                    if position.get("_take_profit_exit"):
                        position["status"] = "watching"
                        position["exit_price"] = current_price
                        position["exit_time"] = time.time()
                        position["exit_reason"] = decision.get("reason", "")
                        log.info(
                            "take_profit_sold_watching",
                            symbol=symbol,
                            exit_price=current_price,
                        )
                    else:
                        position["status"] = "closed"
                        position["exit_price"] = current_price
                        position["exit_time"] = time.time()
                        position["exit_reason"] = decision.get("reason", "")
                    sells_executed += 1

                    # Try to rotate into new token
                    if action == "rotate" or decay.get("severity", 0) >= 5:
                        candidate = find_rotation_candidate(symbol)
                        if candidate:
                            log.info(
                                "rotation_candidate",
                                symbol=candidate.get("symbol"),
                                score=candidate.get("score"),
                            )
                            decision["rotation_candidate"] = candidate.get("symbol")

        elif action == "rotate" and confidence >= 70:
            candidate = find_rotation_candidate(symbol)
            decision["rotation_candidate"] = (
                candidate.get("symbol") if candidate else None
            )
            log.info(
                "rotation_suggested",
                from_token=symbol,
                to_token=decision.get("rotation_candidate"),
            )

        decisions.append(decision)

    # Evaluate watching positions for re-entry
    for wpos in [p for p in positions if p.get("status") == "watching"]:
        sym = wpos.get("symbol", "?")
        addr = wpos.get("address", "")
        chain = wpos.get("chain", "")

        mkt = fetch_token_market_data(addr, chain)
        if not mkt:
            continue
        if sym not in history:
            history[sym] = []
        history[sym].append(mkt)
        dec = detect_decay(sym, mkt, history[sym])

        reentry = evaluate_reentry(wpos, mkt, dec)
        if reentry:
            log.info(
                "reentry_evaluated",
                symbol=sym,
                reenter=reentry.get("reenter"),
                confidence=reentry.get("confidence", 0),
            )
            if reentry.get("reenter") and reentry.get("confidence", 0) >= 70:
                log.info("reentry_recommended", symbol=sym, price=mkt.get("price_usd"))
                wpos["status"] = "reentry_ready"
                wpos["reentry_price"] = mkt.get("price_usd")
                wpos["reentry_confidence"] = reentry.get("confidence")
                decisions.append(
                    {
                        "symbol": sym,
                        "action": "reenter",
                        "reason": reentry.get("reason", ""),
                        "confidence": reentry.get("confidence", 0),
                    }
                )

    # Save updated state
    save_positions(positions)
    save_market_history(history)

    elapsed = time.time() - start

    return {
        "status": "ok",
        "positions_monitored": len(active),
        "sells_executed": sells_executed,
        "decisions": len(decisions),
        "top_decisions": [
            {
                "symbol": d.get("symbol"),
                "action": d.get("action"),
                "confidence": d.get("confidence"),
                "pnl": d.get("pnl_pct"),
            }
            for d in decisions[-5:]
        ],
        "elapsed": round(elapsed, 1),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Trade monitor")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--check-decay", action="store_true")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    result = run_trade_monitor(execute=args.execute, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
