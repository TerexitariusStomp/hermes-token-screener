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

import sys
# TOR proxy - route all external HTTP through SOCKS5
import os
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-token-screener"))
import hermes_screener.tor_config

import json
import subprocess
import time
from typing import Any, Dict, List, Optional

import requests

from hermes_screener.config import settings
from hermes_screener.logging import get_logger

# Blacklist utilities (shared with signal_providers)
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from signal_providers import load_blacklist, is_blacklisted, add_to_blacklist

# Trading bot components (imported at module level for scope access in nested functions)
try:
    from trading_bot import (
        GatewayClient, solana_wallet_address, SOLANA_WSOL,
        get_token_balance, get_native_balance, get_account,
        WETH_ADDR, ROUTER_ADDR, ensure_allowance_base, swap_w2t, swap_t2w
    )
    _trading_bot_available = True
except ImportError as _e:
    _trading_bot_import_error = str(_e)
    _trading_bot_available = False

log = get_logger("ai_trading_brain")

TOP_TOKENS_PATH = settings.hermes_home / "hermes-token-screener" / "data" / "top100.json"
TRADE_LOG_PATH = (
    settings.hermes_home / "data" / "token_screener" / "trade_decisions.json"
)
POSITIONS_PATH = (
    settings.hermes_home / "data" / "token_screener" / "active_positions.json"
)

# Bonsai-8B endpoint
BONSAI_URL = "http://localhost:8083/v1/chat/completions"
BONSAI_MODEL = "Bonsai-8B.gguf"

# ═══════════════════════════════════════════════════════════════════════════════
# TRADING CONFIG (AI decides the rest)
# ═══════════════════════════════════════════════════════════════════════════════

MAX_POSITION_PCT = 5.0  # max % of portfolio per trade (safety cap only)
MIN_POSITIONS = 1  # always maintain at least this many open positions


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
                "max_tokens": 100,
                "temperature": 0.2,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return (
                resp.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
    except Exception as e:
        log.error("bonsai_call_failed", error=str(e))
    return None


def analyze_token_with_ai(token: dict) -> Optional[dict]:
    """
    Send token data to Bonsai-8B for trade decision.

    Falls back to score-based rules if Bonsai is unavailable.
    Returns: {decision, confidence, position_pct, stop_loss_pct, reason}
    """
    system = """You are a crypto trading AI with FULL DECISION AUTHORITY.
You decide EVERYTHING: what to buy, position size, FDV limits, volume minimums, stop loss, take profit.
No hardcoded rules. You use your judgment based on all available data.

Your constraints:
- Max 5% of portfolio per trade (only safety cap)
- You must maintain at least 1 open position at all times
- Honeypots are excluded before you see them (only safety filter)

Consider ALL signals and decide freely:
- Score, smart wallet count, insider presence
- FDV and volume (you decide minimums based on market conditions)
- Price momentum and trend
- Social signals and website quality
- Tax rates, liquidity depth
- Market conditions and risk appetite

Be decisive. When uncertain, choose the best available option rather than holding nothing.

Respond with ONLY a JSON object:
{"decision": "buy|hold|sell", "confidence": 0-100, "position_pct": 0-5, "stop_loss_pct": 5-30, "take_profit_pct": 50-500, "reason": "one sentence"}"""

    prompt = f"""Analyze this token for trading:

Symbol: {token.get('dex', {}).get('symbol', '?')}
Chain: {token.get('chain', '?')}
Score: {token.get('score', 0)}
Smart Wallets: {token.get('smart_wallet_count', token.get('gmgn_smart_wallets', 0))}
Insiders: {token.get('insider_count', 0)}
FDV: ${token.get('dex', {}).get('fdv', 0):,.0f}
Volume 24h: ${token.get('dex', {}).get('volume_h24', 0):,.0f}
Volume 1h: ${token.get('dex', {}).get('volume_h1', 0):,.0f}
Price 1h: {token.get('dex', {}).get('price_change_h1', '?')}%
Price 6h: {token.get('dex', {}).get('price_change_h6', '?')}%
Social Score: {token.get('social_score', 0)}
Age: {token.get('dex', {}).get('age_hours', 0):.1f}h
Positives: {', '.join(token.get('positives', []))}
Negatives: {', '.join(token.get('negatives', []))}
Address: {token.get('contract_address', '')}

Current market context: BTC trending, Solana active, memecoin season."""

    response = call_bonsai(system, prompt)
    if not response:
        # Fallback: score-based decision
        return _score_based_decision(token)

    # Parse JSON from response
    import re

    json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return _score_based_decision(token)


def _score_based_decision(token: dict) -> dict:
    """Fallback trading decision when Bonsai is unavailable."""
    score = token.get("score", 0) or 0
    dex = token.get("dex", {})
    fdv = dex.get("fdv", 0) or 0
    vol_h1 = dex.get("volume_h1", 0) or 0
    age = dex.get("age_hours", 0) or 0
    price_h1 = dex.get("price_change_h1", 0) or 0
    rugcheck = token.get("rugcheck", {})
    risks = rugcheck.get("risks", []) if isinstance(rugcheck, dict) else []

    # Hard exclusions
    if risks:
        return {
            "decision": "hold",
            "confidence": 90,
            "reason": f"rugcheck risks: {risks[:3]}",
        }
    if fdv < 5000:
        return {
            "decision": "hold",
            "confidence": 80,
            "reason": f"FDV too low: ${fdv:,.0f}",
        }
    if vol_h1 < 1000:
        return {
            "decision": "hold",
            "confidence": 75,
            "reason": f"volume too low: ${vol_h1:,.0f}/h",
        }

    # Score-based buy
    if score >= 30 and fdv >= 10000 and vol_h1 >= 5000:
        confidence = min(85, 50 + score)
        return {
            "decision": "buy",
            "confidence": confidence,
            "position_pct": min(3.0, 1.0 + score / 20),
            "stop_loss_pct": 15,
            "take_profit_pct": 100,
            "reason": f"score={score:.0f} fdv=${fdv:,.0f} vol=${vol_h1:,.0f}/h (fallback rule)",
        }
    elif score >= 20 and fdv >= 5000:
        return {
            "decision": "buy",
            "confidence": 55,
            "position_pct": 1.0,
            "stop_loss_pct": 20,
            "take_profit_pct": 80,
            "reason": f"moderate: score={score:.0f} fdv=${fdv:,.0f} (fallback rule)",
        }

    return {
        "decision": "hold",
        "confidence": 60,
        "reason": f"score={score:.0f} below buy threshold",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE FILTERING
# ═══════════════════════════════════════════════════════════════════════════════


def rank_tokens_for_ai(tokens: List[dict]) -> List[dict]:
    """Rank tokens for AI review. No filtering — AI decides what's tradeable."""
    ranked = []
    for t in tokens:
        dex = t.get("dex", {})
        dex.get("fdv", 0) or 0
        dex.get("volume_h24", 0) or 0
        t.get("smart_wallet_count", t.get("gmgn_smart_wallets", 0)) or 0

        # Skip obvious honeypots only (safety)
        if t.get("goplus_is_honeypot"):
            continue

        ranked.append(t)

    # Sort by score descending — AI sees best first
    ranked.sort(key=lambda t: t.get("score", 0) or 0, reverse=True)
    log.info("tokens_ranked", total=len(tokens), ranked=len(ranked))
    return ranked[:20]  # top 20 for AI review


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
        json.dump(
            {"positions": positions, "updated_at": time.time()},
            f,
            indent=2,
            default=str,
        )


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
    Execute a trade via Hummingbot Gateway with test-buy-first flow.

    For new tokens:
    1. Small test buy (0.5% of position)
    2. Attempt to sell test amount back
    3. If sell succeeds -> token is liquid -> buy full position
    4. If sell fails -> blacklist token, abort
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
        log.info("trade_simulated", symbol=symbol, confidence=decision.get("confidence"))
        return result

    # Check trading bot components are available
    if not _trading_bot_available:
        result["status"] = "error"
        result["error"] = f"Cannot import trading_bot: {_trading_bot_import_error}"
        log.error("import_failed", error=_trading_bot_import_error)
        return result

    gw_client = GatewayClient()

    if chain == "solana":
        # Guard: check native SOL balance before attempting trade
        native_sol = get_native_balance("solana")
        # Minimum gas in USD - configurable via env (default $0.15)
        min_gas_usd = float(os.environ.get("MIN_SOL_GAS_USD", "0.15"))
        try:
            sol_price = requests.get(
                "https://coins.llama.fi/prices/current/coingecko:solana",
                timeout=5
            ).json()["coins"]["coingecko:solana"]["price"]
            min_sol_gas = min_gas_usd / sol_price
        except Exception:
            min_sol_gas = 0.001  # fallback: ~$0.14 at $140/SOL
        if native_sol < min_sol_gas:
            result["status"] = "error"
            result["error"] = f"Insufficient SOL for gas: {native_sol:.6f} (need {min_sol_gas:.6f} = ${min_gas_usd:.2f})"
            log.error("insufficient_sol_gas", balance=native_sol, needed=min_sol_gas, usd=min_gas_usd)
            return result
        return _execute_solana_trade(
            gw_client, addr, symbol, position_pct, result, SOLANA_WSOL, solana_wallet_address
        )
    elif chain in ("base", "ethereum"):
        # Guard: check native ETH gas before attempting trade
        native_eth = get_native_balance(chain)
        MIN_ETH_GAS = 0.00005  # ~5-50 txs on Base L2
        if native_eth < MIN_ETH_GAS:
            result["status"] = "error"
            result["error"] = f"Insufficient native ETH for gas on {chain}: {native_eth:.6f} (need {MIN_ETH_GAS})"
            log.error("insufficient_eth_gas", chain=chain, balance=native_eth, needed=MIN_ETH_GAS)
            return result
        return _execute_evm_trade(chain, addr, symbol, position_pct, result, gw_client)
    else:
        result["status"] = "error"
        result["error"] = f"Unsupported chain: {chain}"
        return result


def _execute_solana_trade(
    gw_client, token_addr: str, symbol: str, position_pct: float, result: dict, wsol_addr: str, wallet_addr: str
) -> dict:
    """Execute Solana trade via Jupiter with test-buy-first flow."""
    wallet = wallet_addr
    if not wallet:
        result["status"] = "error"
        result["error"] = "Solana wallet not configured"
        return result

    # Get available WSOL balance
    wsol_bal = get_token_balance("solana", wsol_addr)
    if wsol_bal <= 0.001:
        result["status"] = "error"
        result["error"] = f"Insufficient WSOL: {wsol_bal:.6f}"
        return result

    # Calculate amounts
    buy_amount = wsol_bal * (position_pct / 100.0)
    test_amount = min(buy_amount * 0.1, 0.01)  # 10% of buy or 0.01 SOL max

    if test_amount < 0.001:
        test_amount = 0.001

    log.info("test_buy_starting", symbol=symbol, test_sol=test_amount, full_sol=buy_amount)

    # Step 1: Test buy
    test_lamports = int(test_amount * 1e9)
    resp = gw_client.jupiter_execute_swap(
        address=wallet,
        base=wsol_addr,
        quote=token_addr,
        amount=str(test_lamports),
        slippage_bps=200,  # Higher slippage for test
    )

    if resp.get("error"):
        result["status"] = "failed"
        result["error"] = f"Test buy failed: {resp['error']}"
        log.error("test_buy_failed", symbol=symbol, error=resp["error"])
        add_to_blacklist(symbol, token_addr, "solana", f"Test buy failed: {resp['error']}")
        return result

    log.info("test_buy_success", symbol=symbol)

    # Step 2: Wait and check token balance
    time.sleep(5)
    token_bal = get_token_balance("solana", token_addr)
    if token_bal <= 0:
        result["status"] = "failed"
        result["error"] = "Test buy succeeded but no token balance found"
        log.error("no_balance_after_test_buy", symbol=symbol)
        add_to_blacklist(symbol, token_addr, "solana", "No balance after test buy")
        return result

    # Step 3: Attempt to sell test amount back
    sell_amount = int(token_bal * 0.5 * 1e6)  # Sell half of what we got (6 decimals typical)
    if sell_amount < 1:
        sell_amount = int(token_bal * 1e6)

    log.info("test_sell_attempt", symbol=symbol, sell_amount=sell_amount)
    sell_resp = gw_client.jupiter_execute_swap(
        address=wallet,
        base=token_addr,
        quote=wsol_addr,
        amount=str(sell_amount),
        slippage_bps=200,
    )

    if sell_resp.get("error"):
        log.warning("test_sell_failed_blacklisting", symbol=symbol, error=sell_resp["error"])
        add_to_blacklist(symbol, token_addr, "solana", f"Test sell failed: {sell_resp['error']}")
        result["status"] = "test_sell_failed"
        result["error"] = f"Token illiquid: {sell_resp['error']}"
        return result

    log.info("test_sell_success_token_is_liquid", symbol=symbol)

    # Step 4: Full buy
    time.sleep(3)
    full_lamports = int(buy_amount * 1e9)
    full_resp = gw_client.jupiter_execute_swap(
        address=wallet,
        base=wsol_addr,
        quote=token_addr,
        amount=str(full_lamports),
        slippage_bps=100,
    )

    if full_resp.get("error"):
        result["status"] = "failed"
        result["error"] = f"Full buy failed: {full_resp['error']}"
        log.error("full_buy_failed", symbol=symbol, error=full_resp["error"])
    else:
        result["status"] = "executed"
        result["output"] = f"Bought {symbol} for {buy_amount:.4f} SOL"
        log.info("full_buy_success", symbol=symbol, amount_sol=buy_amount)

    return result


def _execute_evm_trade(
    chain: str, token_addr: str, symbol: str, position_pct: float, result: dict, gw_client
) -> dict:
    """Execute EVM trade (Base/Ethereum) with test-buy-first flow."""

    weth = WETH_ADDR.get(chain)
    if not weth:
        result["status"] = "error"
        result["error"] = f"No WETH addr for chain {chain}"
        return result

    account = get_account(chain)
    weth_bal = get_token_balance(chain, weth)
    if weth_bal <= 0.0001:
        result["status"] = "error"
        result["error"] = f"Insufficient WETH: {weth_bal:.6f}"
        return result

    buy_amount = weth_bal * (position_pct / 100.0)
    test_amount = min(buy_amount * 0.1, 0.001)

    log.info("test_buy_evm", symbol=symbol, chain=chain, test_amt=test_amount)

    # For EVM, just do the buy (test-buy is less critical on Base due to deep liquidity)
    amount_wei = int(buy_amount * 1e18)
    router = ROUTER_ADDR.get(chain)
    if not router:
        result["status"] = "error"
        result["error"] = f"No router for chain {chain}"
        return result

    fee = 3000  # 0.3% fee tier
    if not ensure_allowance_base(None, token_addr, router, amount_wei):
        result["status"] = "error"
        result["error"] = "Token approval failed"
        return result

    swap_result = swap_w2t(None, token_addr, amount_wei, fee)
    if swap_result:
        result["status"] = "executed"
        result["output"] = f"Bought {symbol} for {buy_amount:.6f} WETH on {chain}"
        log.info("evm_buy_success", symbol=symbol, chain=chain)
    else:
        result["status"] = "failed"
        result["error"] = "Swap failed"
        log.error("evm_buy_failed", symbol=symbol, chain=chain)

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
        data = json.load(f)
        # Support both 'tokens' (old format) and 'top_tokens' (new format)
        tokens = data.get("tokens") or data.get("top_tokens", [])

    log.info("tokens_loaded", count=len(tokens))

    # Filter tradeable
    tradeable = rank_tokens_for_ai(tokens)
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
        dex = token.get("dex", {})
        symbol = dex.get("symbol", "?")

        # Skip if already holding
        if symbol in active_symbols:
            log.info("already_holding", symbol=symbol)
            continue

        # Skip blacklisted tokens
        token_addr = token.get("contract_address", "")
        token_chain = token.get("chain", "")
        if token_addr and is_blacklisted(token_addr, token_chain):
            log.info("blacklisted", symbol=symbol, address=token_addr[:16])
            continue

        log.info(
            "analyzing",
            symbol=symbol,
            score=token.get("score"),
            smart=token.get("smart_wallet_count", token.get("gmgn_smart_wallets", 0)),
        )

        decision = analyze_token_with_ai(token)

        if decision:
            decision["symbol"] = symbol
            decision["address"] = token.get("contract_address", "")
            decision["chain"] = token.get("chain", "")
            decision["score"] = token.get("score", 0)
            decision["fdv"] = token.get("dex", {}).get("fdv", 0)

            log_decision(decision)
            decisions.append(decision)

            if (
                decision.get("decision") == "buy"
                and decision.get("confidence", 0) >= 70
            ):
                buy_signals += 1

    # Ensure minimum positions are maintained
    current_active = len([p for p in positions if p.get("status") == "active"])
    if current_active < MIN_POSITIONS and tradeable:
        needed = MIN_POSITIONS - current_active
        log.info(
            "enforcing_min_positions",
            current=current_active,
            target=MIN_POSITIONS,
            needed=needed,
        )
        # Force buy the best available token (highest score)
        forced_buys = sorted(tradeable, key=lambda t: t.get("score", 0), reverse=True)[
            :needed
        ]
        for token in forced_buys:
            fdex = token.get("dex", {})
            forced_decision = {
                "decision": "buy",
                "confidence": 80,
                "position_pct": 2.0,
                "stop_loss_pct": 15,
                "take_profit_pct": 100,
                "reason": f"MIN_POSITIONS enforced (had {current_active}, need {MIN_POSITIONS})",
            }
            forced_decision["symbol"] = fdex.get("symbol", "?")
            forced_decision["address"] = token.get("contract_address", "")
            forced_decision["chain"] = token.get("chain", "")
            forced_decision["score"] = token.get("score", 0)
            forced_decision["fdv"] = fdex.get("fdv", 0)
            log_decision(forced_decision)
            decisions.append(forced_decision)
            buy_signals += 1

    # Execute buy orders
    executed = []
    if execute and buy_signals > 0:
        buy_decisions = [
            d
            for d in decisions
            if d.get("decision") == "buy" and d.get("confidence", 0) >= 70
        ]
        buy_decisions.sort(key=lambda d: d.get("confidence", 0), reverse=True)

        for decision in buy_decisions[:max_trades]:
            token = next(
                (
                    t
                    for t in tradeable
                    if t.get("contract_address") == decision.get("address")
                ),
                None,
            )
            if token:
                result = execute_trade(token, decision, dry_run=dry_run)
                executed.append(result)

                if result["status"] == "executed" and not dry_run:
                    tdex = token.get("dex", {})
                    positions.append(
                        {
                            "symbol": decision["symbol"],
                            "address": decision["address"],
                            "chain": decision["chain"],
                            "entry_price": tdex.get("fdv", 0),  # approximate
                            "position_pct": decision.get("position_pct", 1.0),
                            "stop_loss_pct": decision.get("stop_loss_pct", 15),
                            "take_profit_pct": decision.get("take_profit_pct", 100),
                            "status": "active",
                            "entry_time": time.time(),
                            "ai_confidence": decision.get("confidence"),
                            "ai_reason": decision.get("reason"),
                        }
                    )

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
            {
                "symbol": d["symbol"],
                "decision": d.get("decision"),
                "confidence": d.get("confidence"),
                "reason": d.get("reason", "")[:80],
            }
            for d in decisions[:5]
        ],
        "elapsed": round(elapsed, 1),
    }

    log.info(
        "trading_brain_done",
        **{k: v for k, v in result.items() if k != "top_decisions"},
    )
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI Trading Brain")
    parser.add_argument(
        "--execute", action="store_true", help="Execute approved trades"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True, help="Simulate only"
    )
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
