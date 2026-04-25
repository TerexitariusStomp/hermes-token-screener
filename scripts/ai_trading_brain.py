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
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Set

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
        WETH_ADDR, ROUTER_ADDR, ensure_allowance_base, swap_w2t, swap_t2w,
        gw, gw_eth, wrap_eth, openocean_eth_swap
    )
    _trading_bot_available = True
except ImportError as _e:
    _trading_bot_import_error = str(_e)
    _trading_bot_available = False

log = get_logger("ai_trading_brain")

# Chain normalization — your trading wallet lives on Base, not Ethereum mainnet.
# Token data from the screener may label Base tokens as "ethereum". Map them correctly.
CHAIN_NORMALIZE = {
    'ethereum': 'base',
    'eth': 'base',
    'base': 'base',
    'solana': 'solana',
    'sol': 'solana',
}

def normalize_chain(chain: str) -> str:
    return CHAIN_NORMALIZE.get(chain.lower().strip(), chain.lower())

TOP_TOKENS_PATH = settings.hermes_home / "data" / "token_screener" / "top100.json"
TRADE_LOG_PATH = (
    settings.hermes_home / "data" / "token_screener" / "trade_decisions.json"
)
POSITIONS_PATH = (
    settings.hermes_home / "data" / "token_screener" / "active_positions.json"
)
WALLET_DB_PATH = settings.hermes_home / "data" / "wallet_tracker.db"
WALLETS_JSON_PATH = (
    settings.hermes_home / "data" / "token_screener" / "wallets_phase4_final.json"
)
TRENDING_KEYWORDS_PATH = (
    settings.hermes_home / "data" / "token_screener" / "trending_keywords.json"
)

# Bonsai-8B endpoint
BONSAI_URL = "http://localhost:8083/v1/chat/completions"
BONSAI_MODEL = "Bonsai-8B.gguf"

# ═══════════════════════════════════════════════════════════════════════════════
# TRADING CONFIG (AI decides the rest)
# ═══════════════════════════════════════════════════════════════════════════════

MAX_POSITION_PCT = 5.0  # max % of portfolio per trade (safety cap only)
MIN_POSITIONS = 1  # always maintain at least this many open positions
DECISION_COOLDOWN_SECONDS = 60 * 60  # 1 hour minimum between re-analyzing the same token
MIN_CHAIN_BALANCE = {"solana": 0.001, "base": 0.0005, "ethereum": 0.0005}
EXCLUDE_SYMBOLS = {"WSOL", "WETH", "WBNB", "USDC", "USDT", "DAI", "BUSD", "USDS", "TUSD", "PAX"}


# ═══════════════════════════════════════════════════════════════════════════════
# AI DECISION MAKING
# ═══════════════════════════════════════════════════════════════════════════════


def call_bonsai(system: str, prompt: str, max_tokens: int = 80) -> Optional[str]:
    """Call Bonsai-8B for trading analysis."""
    payload = {
        "model": BONSAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 60,
        "temperature": 0.3,
    }
    try:
        resp = requests.post(BONSAI_URL, json=payload, timeout=600)
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
    """Use Bonsai-8B to analyze a token and decide on a trade."""
    # Load trending keywords inline
    try:
        _kw = json.loads(TRENDING_KEYWORDS_PATH.read_text()) if TRENDING_KEYWORDS_PATH.exists() else {}
        kw_list = [k['keyword'] for k in _kw.get('keywords', [])[:10]]
    except Exception:
        kw_list = []

    # Extract wallet metrics for prompt
    wm = token.get("wallet_metrics", {})
    wallet_block = ""
    if wm:
        tags = wm.get("wallet_tags", "")
        tags_short = ", ".join(tags.split(",")[:3]).strip() if tags else "none"
        wallet_block = (
            f"Wallet Activity: {wm.get('unique_buyers', 0)} buyers, "
            f"${wm.get('total_buy_usd', 0):,.0f} vol, "
            f"avg score {wm.get('avg_wallet_score', 0):.1f}, "
            f"tags: {tags_short}\n"
        )
    else:
        wallet_block = "Wallet Activity: none\n"

    is_synthetic = token.get("is_synthetic", False)
    synthetic_note = ""
    if is_synthetic:
        synthetic_note = "SYNTHETIC: discovered via wallet activity, not in screener.\n"

    system = """You are a crypto trading AI. Decide: buy/hold/sell, position size (0-5%), stop loss (5-30%), take profit (50-500%).
Constraints: max 5% per trade, maintain >=1 position.
Consider: score, smart wallets, insiders, FDV, volume, momentum, social, liquidity, wallet activity.
Respond ONLY with JSON:
{"decision":"buy|hold|sell","confidence":0-100,"position_pct":0-5,"stop_loss_pct":5-30,"take_profit_pct":50-500,"reason":"one sentence"}"""

    dex = token.get("dex", {})
    kw_list = token.get('trending_keywords', [])
    prompt = f"""
Token: {dex.get('symbol', '?')} ({normalize_chain(token.get('chain', '?'))})
Score: {token.get('score', 0)} | Smart: {token.get('smart_wallet_count', token.get('gmgn_smart_wallets', 0))} | Insiders: {token.get('insider_count', 0)}
FDV: ${dex.get('fdv', 0):,.0f} | Vol24h: ${dex.get('volume_h24', 0):,.0f} | Vol1h: ${dex.get('volume_h1', 0):,.0f}
Price: 1h={dex.get('price_change_h1', '?')}% 6h={dex.get('price_change_h6', '?')}% | Social: {token.get('social_score', 0)} | Age: {(dex.get('age_hours') or 0):.1f}h
Pos: {', '.join(token.get('positives', [])[:3])} | Neg: {', '.join(token.get('negatives', [])[:3])}
Trending: {', '.join(kw_list[:3]) if kw_list else 'none'}

{wallet_block}
{synthetic_note}"""

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
        # Skip obvious honeypots only (safety)
        if False:
            continue

        # Compute composite score: screener score + wallet activity boost
        base_score = t.get("score", 0) or 0
        wm = t.get("wallet_metrics", {})
        if wm:
            wallet_boost = min(
                25,
                (wm.get("unique_buyers", 0) * 2)
                + min(10, wm.get("total_buy_usd", 0) / 1000)
                + (wm.get("avg_wallet_score", 0) / 5),
            )
            t["_composite_score"] = base_score + wallet_boost
        else:
            t["_composite_score"] = base_score

        # Boost active-source tokens to prioritize fresh opportunities
        if t.get("source") == "active":
            t["_composite_score"] += 30

        ranked.append(t)

    # Sort by composite score descending — AI sees best first
    ranked.sort(key=lambda t: t.get("_composite_score", 0), reverse=True)
    log.info("tokens_ranked", total=len(tokens), ranked=len(ranked))
    return ranked[:20]  # top 20 for AI review


# ═══════════════════════════════════════════════════════════════════════════════
# WALLET & ACTIVE TOKEN DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════


def load_wallet_quality_map() -> Dict[str, dict]:
    """Load wallet quality data from wallets_phase4_final.json."""
    if not WALLETS_JSON_PATH.exists():
        log.warning("wallets_json_not_found", path=str(WALLETS_JSON_PATH))
        return {}
    try:
        data = json.loads(WALLETS_JSON_PATH.read_text())
        wallets = data.get("wallets", [])
        wallet_map = {}
        for w in wallets:
            addr = w.get("address", "").lower()
            if addr:
                wallet_map[addr] = w
        log.info("wallet_quality_map_loaded", count=len(wallet_map))
        return wallet_map
    except Exception as e:
        log.error("wallet_quality_map_load_failed", error=str(e))
        return {}


def query_active_tokens(hours: int = 24) -> List[dict]:
    """
    Query smart_money_purchases for recent buy activity.
    Returns list of token dicts with wallet-derived metrics.
    """
    if not WALLET_DB_PATH.exists():
        log.warning("wallet_db_not_found", path=str(WALLET_DB_PATH))
        return []

    cutoff = int(time.time() - hours * 3600)
    try:
        conn = sqlite3.connect(f"file:{WALLET_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT token_address, token_symbol, chain, wallet_address, "
            "amount_usd, wallet_score, wallet_tags, timestamp "
            "FROM smart_money_purchases "
            "WHERE side = 'buy' AND timestamp >= ?",
            (cutoff,),
        ).fetchall()
        conn.close()
    except Exception as e:
        log.error("active_tokens_query_failed", error=str(e))
        return []

    # Aggregate by token
    token_map: Dict[str, dict] = {}
    # Skip wrapped/native/stable tokens that aren't trade targets
    SKIP_SYMBOLS = {"wsol", "sol", "weth", "eth", "usdc", "usdt", "wbtc", "btc", "dai"}
    for row in rows:
        sym = (row["token_symbol"] or "?").lower()
        if sym in SKIP_SYMBOLS:
            continue
        key = (row["token_address"] or "").lower()
        if not key:
            continue
        if key not in token_map:
            token_map[key] = {
                "token_address": row["token_address"],
                "symbol": row["token_symbol"] or "?",
                "chain": row["chain"] or "",
                "total_buy_usd": 0.0,
                "unique_buyers": set(),
                "buy_count": 0,
                "last_buy_at": 0,
                "wallet_scores": [],
                "wallet_tags": set(),
            }
        tm = token_map[key]
        tm["total_buy_usd"] += row["amount_usd"] or 0
        tm["unique_buyers"].add(row["wallet_address"])
        tm["buy_count"] += 1
        tm["last_buy_at"] = max(tm["last_buy_at"], row["timestamp"] or 0)
        if row["wallet_score"]:
            tm["wallet_scores"].append(row["wallet_score"])
        if row["wallet_tags"]:
            for tag in str(row["wallet_tags"]).split(","):
                tm["wallet_tags"].add(tag.strip())

    results = []
    for key, tm in token_map.items():
        avg_score = sum(tm["wallet_scores"]) / len(tm["wallet_scores"]) if tm["wallet_scores"] else 0
        results.append({
            "token_address": tm["token_address"],
            "symbol": tm["symbol"],
            "chain": tm["chain"],
            "total_buy_usd": round(tm["total_buy_usd"], 2),
            "unique_buyers": len(tm["unique_buyers"]),
            "buy_count": tm["buy_count"],
            "avg_wallet_score": round(avg_score, 1),
            "last_buy_at": tm["last_buy_at"],
            "wallet_tags": ",".join(sorted(tm["wallet_tags"])) if tm["wallet_tags"] else "",
        })

    # Sort by unique buyers then total buy USD
    results.sort(key=lambda x: (x["unique_buyers"], x["total_buy_usd"]), reverse=True)
    log.info("active_tokens_queried", count=len(results), hours=hours)
    return results



def query_cross_tokens(limit: int = 200) -> List[dict]:
    """
    Query tokens held by top smart-money wallets (tracked_wallets with wallet_score >= 20).
    Returns synthetic token dicts with wallet-derived metrics — complements active_tokens.
    """
    if not WALLET_DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{WALLET_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT 
                smp.token_address,
                smp.token_symbol,
                smp.chain,
                COUNT(DISTINCT smp.wallet_address) as holder_count,
                SUM(smp.amount_usd) as total_buy_usd,
                AVG(smp.wallet_score) as avg_wallet_score,
                MAX(smp.timestamp) as last_buy_at,
                GROUP_CONCAT(DISTINCT smp.wallet_tags) as wallet_tags_raw
            FROM smart_money_purchases smp
            JOIN tracked_wallets tw ON smp.wallet_address = tw.address
            WHERE tw.wallet_score >= 20
            GROUP BY smp.token_address
            ORDER BY holder_count DESC, last_buy_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        conn.close()
    except Exception as e:
        log.error("cross_tokens_query_failed", error=str(e))
        return []

    results = []
    for row in rows:
        addr = row["token_address"] or ""
        sym = row["token_symbol"] or "?"
        chain = row["chain"] or ""
        holder_count = row["holder_count"] or 0
        total_buy = row["total_buy_usd"] or 0.0
        avg_score = row["avg_wallet_score"] or 0.0
        last_ts = row["last_buy_at"] or 0
        tags_raw = row["wallet_tags_raw"] or ""
        tags_set = {t.strip() for t in tags_raw.split(",") if t.strip()}

        synthetic_score = min(
            70,
            holder_count * 3 + min(20, total_buy / 1000) + (avg_score / 4)
        )

        results.append({
            "contract_address": addr,
            "chain": chain,
            "symbol": sym,
            "score": round(synthetic_score, 1),
            "dex": {
                "symbol": sym,
                "fdv": 0,
                "volume_h24": 0,
                "volume_h1": 0,
                "price_change_h1": 0,
                "price_change_h6": 0,
                "age_hours": 0,
            },
            "smart_wallet_count": holder_count,
            "wallet_metrics": {
                "unique_buyers": holder_count,
                "total_buy_usd": round(total_buy, 2),
                "avg_wallet_score": round(avg_score, 1),
                "buy_count": holder_count,
                "wallet_tags": ",".join(sorted(tags_set)),
                "last_buy_at": last_ts,
            },
            "_composite_score": round(synthetic_score, 1),
            "is_synthetic": True,
            "source": "cross_tokens",
        })

    log.info("cross_tokens_loaded", count=len(results))
    return results

def enrich_and_merge_tokens(
    top_tokens: List[dict],
    active_tokens: List[dict],
    wallet_map: Dict[str, dict],
    cross_tokens: List[dict] = [],
) -> List[dict]:
    """
    Enrich top100 tokens with wallet metrics and inject synthetic tokens
    for active purchases not present in the screener.
    """
    # Build lookup by normalized address
    top_by_addr: Dict[str, dict] = {}
    for t in top_tokens:
        addr = (t.get("contract_address") or "").lower()
        if addr:
            top_by_addr[addr] = t

    # Enrich existing top tokens with wallet metrics
    for at in active_tokens:
        addr = (at.get("token_address") or "").lower()
        if addr in top_by_addr:
            t = top_by_addr[addr]
            t["wallet_metrics"] = {
                "unique_buyers": at["unique_buyers"],
                "total_buy_usd": at["total_buy_usd"],
                "avg_wallet_score": at["avg_wallet_score"],
                "buy_count": at["buy_count"],
                "wallet_tags": at["wallet_tags"],
                "last_buy_at": at["last_buy_at"],
            }

    # Build synthetic tokens for active tokens not in top100
    synthetic: List[dict] = []
    for at in active_tokens:
        addr = (at.get("token_address") or "").lower()
        if addr in top_by_addr:
            continue
        # Compute synthetic score from wallet activity
        synthetic_score = min(
            70,
            at["unique_buyers"] * 8
            + at["buy_count"] * 1.5
            + min(15, at["total_buy_usd"] / 500)
            + at["avg_wallet_score"] / 3,
        )
        sym = at["symbol"]
        chain = at["chain"]
        st = {
            "contract_address": at["token_address"],
            "chain": chain,
            "score": round(synthetic_score, 1),
            "dex": {
                "symbol": sym,
                "fdv": 0,
                "volume_h24": 0,
                "volume_h1": 0,
                "price_change_h1": 0,
                "price_change_h6": 0,
                "age_hours": 0,
                "description": "",
            },
            "smart_wallet_count": at["unique_buyers"],
            "insider_count": 0,
            "social_score": 0,
            "positives": [f"{at['unique_buyers']} smart wallets buying"],
            "negatives": ["Not in screener top100 — discovered via wallet activity"],
            "wallet_metrics": {
                "unique_buyers": at["unique_buyers"],
                "total_buy_usd": at["total_buy_usd"],
                "avg_wallet_score": at["avg_wallet_score"],
                "buy_count": at["buy_count"],
                "wallet_tags": at["wallet_tags"],
                "last_buy_at": at["last_buy_at"],
            },
            "is_synthetic": True,
            "source": "active",
        }
        synthetic.append(st)

    log.info(
        "tokens_enriched_and_merged",
        top_count=len(top_tokens),
        active_count=len(active_tokens),
        synthetic_count=len(synthetic),
        enriched_count=len([t for t in top_tokens if "wallet_metrics" in t]),
        cross_count=len(cross_tokens),
    )
    # Merge with deduplication: prefer richer source data
    # Priority: top_tokens (full screener) > synthetic (active not in top100) > cross_tokens (wallet-held not in top100)
    all_by_addr: dict[str, dict] = {}
    # Order-preserving insertion: later duplicates won't override if we control order
    # Build lookup: keep first occurrence in priority order
    for t in top_tokens + synthetic + cross_tokens:
        addr = (t.get("contract_address") or "").lower()
        if addr:
            all_by_addr.setdefault(addr, t)  # first wins (top_tokens before synthetic before cross)
    results = list(all_by_addr.values())
    log.info("tokens_final_merge", total=len(results), top=len(top_tokens), synthetic=len(synthetic), cross=len(cross_tokens))
    return results


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
    # Normalize chain — ensures Base tokens labeled 'ethereum' query the correct RPC
    chain = normalize_chain(token.get("chain", ""))
    addr = token.get("contract_address", "")
    # Symbol may be at top level or nested in dex dict
    symbol = token.get("symbol") or token.get("dex", {}).get("symbol", "?")
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
        try:
            native_sol = get_native_balance("solana")
        except Exception as e:
            result["status"] = "error"
            result["error"] = f"Solana balance check failed: {e}"
            log.error("sol_balance_check_failed", error=str(e))
            return result
        # Minimum gas in USD - configurable via env (default $0.15)
        min_gas_usd = float(os.environ.get("MIN_SOL_GAS_USD", "0.15"))
        try:
            sol_price = requests.get(
                "https://coins.llama.fi/prices/current/coingecko:solana",
                timeout=5
            ).json()["coins"]["coingecko:solana"]["price"]
            min_sol_gas = min_gas_usd / sol_price
        except Exception:
            min_sol_gas = 0.001  # fallback: ~$0.15 at $150/SOL
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
        try:
            native_eth = get_native_balance(chain)
        except Exception as e:
            result["status"] = "error"
            result["error"] = f"Base balance check failed: {e}"
            log.error("base_balance_check_failed", error=str(e))
            return result
        # Minimum gas in USD - configurable via env (default $0.05)
        min_eth_gas_usd = float(os.environ.get("MIN_ETH_GAS_USD", "0.05"))
        try:
            eth_price = requests.get(
                "https://coins.llama.fi/prices/current/coingecko:ethereum",
                timeout=5
            ).json()["coins"]["coingecko:ethereum"]["price"]
            min_eth_gas = min_eth_gas_usd / eth_price
        except Exception:
            min_eth_gas = 0.00002  # fallback: ~$0.05 at $2500/ETH
        if native_eth < min_eth_gas:
            result["status"] = "error"
            result["error"] = f"Insufficient native ETH for gas on {chain}: {native_eth:.6f} (need {min_eth_gas:.6f} = ${min_eth_gas_usd:.2f})"
            log.error("insufficient_eth_gas", chain=chain, balance=native_eth, needed=min_eth_gas)
            return result

        # Verify token actually exists on the claimed chain before wasting gas on approvals
        if not is_token_on_chain(addr, chain, expected_symbol=symbol):
            result["status"] = "error"
            result["error"] = f"Token {symbol} ({addr}) not found on {chain} — wrong chain in metadata"
            log.error("token_not_on_chain", symbol=symbol, addr=addr, chain=chain)
            add_to_blacklist(symbol, addr, chain, f"wrong chain metadata (claimed {chain})")
            return result

        return _execute_evm_trade(chain, addr, symbol, position_pct, result)
    else:
        result["status"] = "error"
        result["error"] = f"Unsupported chain: {chain}"
        return result


def _is_pumpfun_token(mint: str) -> dict | None:
    """Return pump.fun token info dict if mint is a pump.fun token, else None."""
    rpc = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    try:
        cmd = [
            "pumpfun",
            "--rpc", rpc,
            "info",
            mint,
            "--json",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        info = json.loads(result.stdout)
        if info.get("bonding_curve") or info.get("graduated") is not None:
            return info
        return None
    except Exception:
        return None


def _execute_pumpfun_solana_trade(
    token_addr: str,
    symbol: str,
    position_pct: float,
    result: dict,
    wallet_addr: str,
    pump_info: dict,
) -> dict:
    """Execute a Solana trade via pump.fun bonding curve or PumpSwap AMM."""
    wallet = wallet_addr
    is_graduated = pump_info.get("graduated", False)
    venue = "pumpswap" if is_graduated else "pumpfun-bonding"
    force_amm = ["--force-amm"] if is_graduated else []
    rpc = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

    # Use native SOL balance
    try:
        native_sol = get_native_balance("solana")
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Solana balance check failed: {e}"
        log.error("sol_balance_check_failed", error=str(e))
        return result
    min_sol_trade = 0.0001  # dust floor only — gas guard already passed
    if native_sol < min_sol_trade:
        result["status"] = "error"
        result["error"] = f"Insufficient SOL: {native_sol:.6f} (need {min_sol_trade:.6f})"
        return result

    buy_amount = native_sol * (position_pct / 100.0)
    test_amount = min(buy_amount * 0.1, 0.01)
    if test_amount < 0.001:
        test_amount = 0.001

    log.info("pumpfun_test_buy_starting", symbol=symbol, venue=venue, test_sol=test_amount)

    # Step 1: Test buy via pumpfun
    try:
        cmd = [
            "pumpfun", "--rpc", rpc,
            "buy", token_addr, str(test_amount),
        ] + force_amm + ["--confirm"]
        buy_result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if buy_result.returncode != 0:
            result["status"] = "failed"
            result["error"] = f"Pump.fun test buy failed: {buy_result.stderr.strip()}"
            log.error("pumpfun_test_buy_failed", symbol=symbol, error=buy_result.stderr.strip())
            add_to_blacklist(symbol, token_addr, "solana", result["error"])
            return result
        log.info("pumpfun_test_buy_success", symbol=symbol, stdout=buy_result.stdout.strip())
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Pump.fun test buy exception: {e}"
        log.error("pumpfun_test_buy_exception", symbol=symbol, error=str(e))
        return result

    # Step 2: Wait and check token balance
    time.sleep(5)
    token_bal = get_token_balance("solana", token_addr)
    if token_bal <= 0:
        result["status"] = "failed"
        result["error"] = "Pump.fun test buy succeeded but no token balance found"
        log.error("pumpfun_no_balance_after_test_buy", symbol=symbol)
        add_to_blacklist(symbol, token_addr, "solana", result["error"])
        return result

    # Step 3: Attempt test sell
    sell_amount = token_bal * 0.5
    if sell_amount < 1e-9:
        sell_amount = token_bal
    log.info("pumpfun_test_sell_attempt", symbol=symbol, sell_amount=sell_amount)
    try:
        cmd = [
            "pumpfun", "--rpc", rpc,
            "sell", token_addr, "all",
        ] + force_amm + ["--confirm"]
        sell_result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if sell_result.returncode != 0:
            log.warning("pumpfun_test_sell_failed_blacklisting", symbol=symbol, error=sell_result.stderr.strip())
            add_to_blacklist(symbol, token_addr, "solana", f"Pump.fun test sell failed: {sell_result.stderr.strip()}")
            result["status"] = "test_sell_failed"
            result["error"] = f"Token illiquid on pump.fun: {sell_result.stderr.strip()}"
            return result
        log.info("pumpfun_test_sell_success", symbol=symbol, stdout=sell_result.stdout.strip())
    except Exception as e:
        log.warning("pumpfun_test_sell_exception", symbol=symbol, error=str(e))
        add_to_blacklist(symbol, token_addr, "solana", f"Pump.fun test sell exception: {e}")
        result["status"] = "test_sell_failed"
        result["error"] = f"Pump.fun test sell exception: {e}"
        return result

    # Step 4: Full buy via pumpfun
    time.sleep(3)
    log.info("pumpfun_full_buy_starting", symbol=symbol, amount_sol=buy_amount, venue=venue)
    try:
        cmd = [
            "pumpfun", "--rpc", rpc,
            "buy", token_addr, str(buy_amount),
        ] + force_amm + ["--confirm"]
        full_result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if full_result.returncode != 0:
            result["status"] = "failed"
            result["error"] = f"Pump.fun full buy failed: {full_result.stderr.strip()}"
            log.error("pumpfun_full_buy_failed", symbol=symbol, error=full_result.stderr.strip())
        else:
            result["status"] = "executed"
            result["output"] = f"Bought {symbol} for {buy_amount:.4f} SOL via {venue}"
            log.info("pumpfun_full_buy_success", symbol=symbol, amount_sol=buy_amount, venue=venue)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Pump.fun full buy exception: {e}"
        log.error("pumpfun_full_buy_exception", symbol=symbol, error=str(e))

    return result


def is_token_on_chain(token_addr: str, chain: str, expected_symbol: str = None) -> bool:
    """
    Verify a token actually exists on the given chain and optionally matches
    the expected symbol. Skips verification for native ETH address.
    """
    NATIVE_ETH = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
    if token_addr.upper() == NATIVE_ETH.upper():
        return True
    ERC20_SYMBOL_ABI = [
        {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}],
         "stateMutability": "view", "type": "function"},
    ]
    try:
        w = gw() if chain == "base" else gw_eth()
        if not w:
            return True  # assume OK if we can't check
        checksum = Web3.to_checksum_address(token_addr)
        code = w.eth.get_code(checksum)
        if len(code) <= 2:
            return False
        # Symbol check: verify this is the right token contract
        if expected_symbol:
            try:
                token = w.eth.contract(address=checksum, abi=ERC20_SYMBOL_ABI)
                actual = token.functions.symbol().call()
                if actual.upper() != expected_symbol.upper():
                    return False
            except Exception:
                # If symbol check fails, fall back to code-only check
                pass
        return True
    except Exception:
        return True  # assume OK on error


def _execute_solana_trade(
    gw_client, token_addr: str, symbol: str, position_pct: float, result: dict, wsol_addr: str, wallet_addr: str
) -> dict:
    """Execute Solana trade via Jupiter with test-buy-first flow."""
    wallet = wallet_addr
    if not wallet:
        result["status"] = "error"
        result["error"] = "Solana wallet not configured"
        return result

    # --- Pump.fun / PumpSwap priority ---
    pump_info = _is_pumpfun_token(token_addr)
    if pump_info:
        venue = "pumpswap" if pump_info.get("graduated") else "pumpfun-bonding"
        log.info("pumpfun_token_detected", symbol=symbol, venue=venue, mint=token_addr)
        return _execute_pumpfun_solana_trade(
            token_addr, symbol, position_pct, result, wallet_addr, pump_info
        )

    # Use native SOL balance (Jupiter auto-wraps SOL->WSOL)
    try:
        native_sol = get_native_balance("solana")
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Solana balance check failed: {e}"
        log.error("sol_balance_check_failed", error=str(e))
        return result
    min_sol_trade = float(os.environ.get("MIN_SOL_GAS_USD", "0.15")) / 150.0  # ~0.001 SOL fallback
    try:
        sol_price = requests.get(
            "https://coins.llama.fi/prices/current/coingecko:solana",
            timeout=5
        ).json()["coins"]["coingecko:solana"]["price"]
        min_sol_trade = 0.15 / sol_price
    except Exception:
        pass
    if native_sol < min_sol_trade:
        result["status"] = "error"
        result["error"] = f"Insufficient SOL: {native_sol:.6f} (need {min_sol_trade:.6f})"
        return result

    # Calculate amounts from native SOL
    buy_amount = native_sol * (position_pct / 100.0)
    test_amount = min(buy_amount * 0.1, 0.01)  # 10% of buy or 0.01 SOL max
    # No hardcoded floor — trade as long as gas guard passed

    log.info("test_buy_starting", symbol=symbol, test_sol=test_amount, full_sol=buy_amount)

    # Step 1: Test buy
    resp = gw_client.jupiter_execute_swap(
        wallet_address=wallet,
        base_token=token_addr,
        quote_token=wsol_addr,
        amount=test_amount,
        side="BUY",
        slippage_pct=2.0,
    )

    if resp.get("error"):
        err_msg = resp.get("error", "")
        log.error("test_buy_failed", symbol=symbol, error=err_msg)
        
        # Fallback 1: Try Raydium direct if Jupiter returned NO_ROUTES_FOUND
        if "NO_ROUTES_FOUND" in err_msg or "no route" in err_msg.lower():
            log.info("jupiter_no_routes_fallback", symbol=symbol, venue="raydium")
            # Try Raydium direct swap via Gateway
            try:
                ray_resp = gw_client._post(
                    "/connectors/raydium/swap",
                    {
                        "walletAddress": wallet,
                        "network": "mainnet-beta",
                        "baseToken": token_addr,
                        "quoteToken": wsol_addr,
                        "amount": test_amount,
                        "side": "BUY",
                        "slippagePct": 5.0,
                    },
                )
                if ray_resp.get("error"):
                    result["status"] = "failed"
                    result["error"] = f"Raydium fallback failed: {ray_resp['error']}"
                    add_to_blacklist(symbol, token_addr, "solana", f"Raydium test buy failed: {ray_resp['error']}")
                    return result
                # Raydium test buy succeeded — continue with flow (same Jupiter flow but use Raydium for subsequent swaps)
                log.info("raydium_test_buy_success", symbol=symbol)
                # Replace gw_client with raydium wrapper for subsequent calls
                def ray_swap(side: str, amt: float):
                    return gw_client._post(
                        "/connectors/raydium/swap",
                        {
                            "walletAddress": wallet,
                            "network": "mainnet-beta",
                            "baseToken": token_addr,
                            "quoteToken": wsol_addr,
                            "amount": amt,
                            "side": side,
                            "slippagePct": 2.0 if side == "BUY" else 5.0,
                        },
                    )
                # Continue to step 2 with Raydium
                # (Same balance check and sell test)
                time.sleep(5)
                token_bal = get_token_balance("solana", token_addr)
                if token_bal <= 0:
                    result["status"] = "failed"
                    result["error"] = "Raydium test buy succeeded but no token balance found"
                    add_to_blacklist(symbol, token_addr, "solana", "No balance after test buy")
                    return result
                sell_amount = token_bal * 0.5
                if sell_amount < 1e-9:
                    sell_amount = token_bal
                sell_resp = ray_swap("SELL", sell_amount)
                if sell_resp.get("error"):
                    add_to_blacklist(symbol, token_addr, "solana", f"Raydium test sell failed: {sell_resp['error']}")
                    result["status"] = "test_sell_failed"
                    result["error"] = f"Token illiquid: {sell_resp['error']}"
                    return result
                log.info("raydium_test_sell_success", symbol=symbol)
                time.sleep(3)
                full_resp = ray_swap("BUY", buy_amount)
                if full_resp.get("error"):
                    result["status"] = "failed"
                    result["error"] = f"Raydium full buy failed: {full_resp['error']}"
                else:
                    result["status"] = "executed"
                    result["output"] = f"Bought {symbol} for {buy_amount:.4f} SOL via Raydium"
                    log.info("raydium_full_buy_success", symbol=symbol, amount_sol=buy_amount)
                return result
            except Exception as e:
                result["status"] = "failed"
                result["error"] = f"Raydium fallback exception: {e}"
                return result
        # Fallback 2: Pumpfun CLI (only if token is a pump token)
        if _is_pumpfun_token(token_addr):
            log.info("fallback_to_pumpfun", symbol=symbol)
            # Delegate to pumpfun execution path
            pump_info = _is_pumpfun_token(token_addr)
            return _execute_pumpfun_solana_trade(token_addr, symbol, position_pct, result, wallet_addr, pump_info)
        # All fallbacks exhausted
        result["status"] = "failed"
        result["error"] = f"Test buy failed: {err_msg}"
        add_to_blacklist(symbol, token_addr, "solana", f"Test buy failed: {err_msg}")
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
    sell_amount = token_bal * 0.5  # Sell half of what we got
    if sell_amount < 1e-9:
        sell_amount = token_bal

    log.info("test_sell_attempt", symbol=symbol, sell_amount=sell_amount)
    sell_resp = gw_client.jupiter_execute_swap(
        wallet_address=wallet,
        base_token=token_addr,
        quote_token=wsol_addr,
        amount=sell_amount,
        side="SELL",
        slippage_pct=2.0,
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
    full_resp = gw_client.jupiter_execute_swap(
        wallet_address=wallet,
        base_token=token_addr,
        quote_token=wsol_addr,
        amount=buy_amount,
        side="BUY",
        slippage_pct=1.0,
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
    chain: str, token_addr: str, symbol: str, position_pct: float, result: dict
) -> dict:
    """Execute EVM trade (Base/Ethereum) with test-buy-first flow."""

    # Use native ETH balance directly — OpenOcean handles the swap without wrapping
    try:
        native_bal = get_native_balance(chain)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{chain} balance check failed: {e}"
        log.error("evm_balance_check_failed", chain=chain, error=str(e))
        return result

    if native_bal <= 0.0001:
        result["status"] = "error"
        result["error"] = f"Insufficient native ETH: {native_bal:.6f}"
        return result

    buy_amount = native_bal * (position_pct / 100.0)
    if buy_amount < 0.00001:
        result["status"] = "error"
        result["error"] = f"Trade amount too small: {buy_amount:.6f} ETH"
        return result

    amount_wei = int(buy_amount * 1e18)
    log.info("native_eth_trade", symbol=symbol, chain=chain, amount_eth=buy_amount)

    # OpenOcean swap: direct ETH → token, no wrap needed
    w = gw()
    if not w:
        result["status"] = "error"
        result["error"] = "Base Web3 unavailable"
        return result

    ok = openocean_eth_swap(w, token_addr, amount_wei)
    if ok:
        result["status"] = "executed"
        result["output"] = f"Bought {symbol} for {buy_amount:.6f} ETH on {chain} via OpenOcean"
        log.info("native_eth_buy_success", symbol=symbol, chain=chain)
    else:
        result["status"] = "failed"
        result["error"] = "OpenOcean swap failed"
        log.error("native_eth_buy_failed", symbol=symbol, chain=chain)
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
        top_tokens = data.get("tokens") or data.get("top_tokens", [])

    log.info("tokens_loaded", count=len(top_tokens))

    # ── Load wallet quality map and active tokens ──────────────────────────
    wallet_map = load_wallet_quality_map()
    active_tokens = query_active_tokens(hours=24)
    cross_tokens = query_cross_tokens(limit=200)
    all_tokens = enrich_and_merge_tokens(top_tokens, active_tokens, wallet_map, cross_tokens)
    # Exclude wrapped/stable symbols — not real opportunities
    filtered_tokens = [
        t for t in all_tokens
        if (t.get("dex", {}).get("symbol", "").upper() not in EXCLUDE_SYMBOLS)
        and (t.get("symbol", "").upper() not in EXCLUDE_SYMBOLS)
    ]
    # Deduplicate by address — keep first occurrence (preserves priority order: top > synthetic > cross)
    seen_addrs: set[str] = set()
    deduped: list[dict] = []
    for t in filtered_tokens:
        addr = (t.get("contract_address") or "").lower()
        if addr and addr not in seen_addrs:
            seen_addrs.add(addr)
            deduped.append(t)
    log.info("tokens_after_exclusion", total=len(all_tokens), excluded=len(all_tokens)-len(deduped), remaining=len(deduped))
    filtered_tokens = deduped

    # Filter tradeable
    tradeable = rank_tokens_for_ai(filtered_tokens)
    if not tradeable:
        log.info("no_tradeable_tokens")
        return {"status": "no_tradeable", "tokens_analyzed": len(all_tokens)}

    # Check existing positions
    positions = load_positions()
    active_symbols = {p.get("symbol") for p in positions if p.get("status") == "active"}

    # Analyze with AI — but only tokens on chains where we have funded wallets
    decisions = []
    buy_signals = 0

    # Determine which chains are funded
    funded_chains = []
    for ch, bal in [("solana", None), ("base", None), ("ethereum", None)]:
        try:
            bal = get_native_balance(ch) if ch != "solana" else get_native_balance("solana")
            min_bal = MIN_CHAIN_BALANCE.get(ch, 0.0001)
            if bal >= min_bal:
                funded_chains.append(ch)
            else:
                log.info("chain_no_funds", chain=ch, balance=bal, min_required=min_bal)
        except Exception as e:
            log.error("chain_balance_check_failed", chain=ch, error=str(e))

    log.info("funded_chains", chains=funded_chains)

    # Filter to tokens on funded chains only
    tradeable_funded = [
        t for t in tradeable
        if normalize_chain(t.get("chain", "")) in funded_chains
    ]
    if not tradeable_funded:
        log.info("no_tokens_on_funded_chains", funded=funded_chains,
                 total_tradeable=len(tradeable))
        return {"status": "no_funded_chains", "funded_chains": funded_chains}

    tokens_to_analyze = tradeable_funded[:20]
    log.info("analyzing_funded_chains", chains=[normalize_chain(t.get("chain","")) for t in tokens_to_analyze])

    # ── Load recent decisions for cooldown ────────────────────────────────────
    recent_decisions: dict[str, float] = {}
    if TRADE_LOG_PATH.exists():
        try:
            with open(TRADE_LOG_PATH) as f:
                history = json.load(f)
            for d in history[-200:]:
                sym = (d.get("symbol", "") or "").upper()
                if sym:
                    recent_decisions[sym] = max(
                        recent_decisions.get(sym, 0), d.get("timestamp", 0)
                    )
        except Exception:
            pass

    for token in tokens_to_analyze:
        dex = token.get("dex", {})
        symbol = dex.get("symbol", "?")
        # Skip if analyzed recently
        last_decided = recent_decisions.get(symbol.upper(), 0)
        if time.time() - last_decided < DECISION_COOLDOWN_SECONDS:
            log.info("skipped_cooldown", symbol=symbol, age_sec=int(time.time() - last_decided))
            continue

        # Skip if already holding
        if symbol in active_symbols:
            log.info("already_holding", symbol=symbol)
            continue

        # Skip blacklisted tokens
        token_addr = token.get("contract_address", "")
        token_chain = normalize_chain(token.get("chain", ""))
        if token_addr and is_blacklisted(token_addr, token_chain):
            log.info("blacklisted", symbol=symbol, address=token_addr[:16])
            continue

        log.info(
            "analyzing",
            symbol=symbol,
            score=token.get("score"),
            composite=token.get("_composite_score"),
            smart=token.get("smart_wallet_count", token.get("gmgn_smart_wallets", 0)),
            wallets=token.get("wallet_metrics", {}).get("unique_buyers", 0),
            synthetic=token.get("is_synthetic", False),
        )

        decision = analyze_token_with_ai(token)

        if decision:
            decision["symbol"] = symbol
            decision["address"] = token.get("contract_address", "")
            decision["chain"] = normalize_chain(token.get("chain", ""))
            decision["score"] = token.get("score", 0)
            decision["fdv"] = token.get("dex", {}).get("fdv", 0)
            decision["is_synthetic"] = token.get("is_synthetic", False)

            log_decision(decision)
            decisions.append(decision)

            if (
                decision.get("decision") == "buy"
                and decision.get("confidence", 0) >= 70
            ):
                buy_signals += 1

    # Ensure minimum positions are maintained — only from funded chains
    current_active = len([p for p in positions if p.get("status") == "active"])
    if current_active < MIN_POSITIONS and tradeable_funded:
        needed = MIN_POSITIONS - current_active
        log.info(
            "enforcing_min_positions", current=current_active, target=MIN_POSITIONS, needed=needed,
        )
        # Force buy the best available token (highest composite score)
        forced_buys = sorted(tradeable_funded, key=lambda t: t.get("_composite_score", 0), reverse=True)[:needed]
        for token in forced_buys:
            # Skip blacklisted tokens in forced buy path too
            ftoken_addr = token.get("contract_address", "")
            ftoken_chain = normalize_chain(token.get("chain", ""))
            if ftoken_addr and is_blacklisted(ftoken_addr, ftoken_chain):
                log.info("blacklisted_forced_buy_skipped", 
                         symbol=token.get("dex", {}).get("symbol", "?"),
                         address=ftoken_addr[:16])
                continue
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
            forced_decision["chain"] = normalize_chain(token.get("chain", ""))
            forced_decision["score"] = token.get("score", 0)
            forced_decision["fdv"] = fdex.get("fdv", 0)
            forced_decision["is_synthetic"] = token.get("is_synthetic", False)
            log_decision(forced_decision)
            decisions.append(forced_decision)
            buy_signals += 1

    # Execute buy orders
    executed = []
    executed_success = 0
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
                log.info(
                    "trade_attempt_result",
                    symbol=decision.get("symbol", "?"),
                    chain=decision.get("chain", ""),
                    status=result.get("status"),
                    error=result.get("error", ""),
                )

                if result.get("status") == "executed":
                    executed_success += 1

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
                            "is_synthetic": decision.get("is_synthetic", False),
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
        "executed": executed_success,
        "execution_attempts": len(executed),
        "active_positions": len([p for p in positions if p.get("status") == "active"]),
        "top_decisions": [
            {
                "symbol": d["symbol"],
                "decision": d.get("decision"),
                "confidence": d.get("confidence"),
                "reason": d.get("reason", "")[:80],
                "is_synthetic": d.get("is_synthetic", False),
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
