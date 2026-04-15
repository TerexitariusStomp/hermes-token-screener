"""
Token Lifecycle Tracker — Captures chart data from entry to exit.

For each token that qualifies as a top token:
  - Snapshot OHLCV data when it first enters the database
  - Update snapshot periodically while it remains
  - Final snapshot when it exits (no longer qualifies)
  - Generate comparison chart: entry price vs exit price

Storage:
  ~/.hermes/data/token_screener/lifecycle/{address}_lifecycle.json
  ~/.hermes/data/token_screener/lifecycle/{address}_entry.png
  ~/.hermes/data/token_screener/lifecycle/{address}_exit.png

Usage:
    python3 token_lifecycle.py                    # run lifecycle tracking
    python3 token_lifecycle.py --snapshot         # force snapshot all current tokens
    python3 token_lifecycle.py --chart <address>  # generate lifecycle chart
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from hermes_screener.config import settings
from hermes_screener.logging import get_logger
from hermes_screener.metrics import metrics

log = get_logger("token_lifecycle")

LIFECYCLE_DIR = settings.hermes_home / "data" / "token_screener" / "lifecycle"
TOP_TOKENS_PATH = settings.output_path

# GeckoTerminal network mapping
_GT_NETWORKS = {
    "solana": "solana", "sol": "solana",
    "ethereum": "eth", "eth": "eth",
    "base": "base",
    "binance": "bsc", "bsc": "bsc", "binance-smart-chain": "bsc",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

def _lifecycle_path(address: str) -> Path:
    return LIFECYCLE_DIR / f"{address}_lifecycle.json"


def _load_lifecycle(address: str) -> Optional[dict]:
    path = _lifecycle_path(address)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _save_lifecycle(address: str, data: dict):
    LIFECYCLE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_lifecycle_path(address), "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_current_tokens() -> List[dict]:
    if TOP_TOKENS_PATH.exists():
        with open(TOP_TOKENS_PATH) as f:
            return json.load(f).get("tokens", [])
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# OHLCV SNAPSHOT
# ═══════════════════════════════════════════════════════════════════════════════

async def _find_pool(chain: str, address: str, client: httpx.AsyncClient) -> Optional[str]:
    """Find top pool address for a token."""
    net = _GT_NETWORKS.get(chain.lower(), "solana")
    try:
        resp = await client.get(
            f"https://api.geckoterminal.com/api/v2/networks/{net}/tokens/{address}/pools",
            params={"sort": "h24_tx_count_desc", "page": "1"},
            timeout=10,
        )
        if resp.status_code == 200:
            pools = resp.json().get("data", [])
            if pools:
                pool_id = pools[0]["id"]
                return pool_id.split("_")[-1] if "_" in pool_id else pool_id
    except Exception:
        pass
    return None


async def _fetch_ohlcv(chain: str, pool: str, timeframe: str, limit: int,
                        client: httpx.AsyncClient) -> List[list]:
    """Fetch OHLCV candles from GeckoTerminal."""
    net = _GT_NETWORKS.get(chain.lower(), "solana")
    try:
        resp = await client.get(
            f"https://api.geckoterminal.com/api/v2/networks/{net}/pools/{pool}/ohlcv/{timeframe}",
            params={"aggregate": "1", "limit": str(limit)},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])
    except Exception:
        pass
    return []


async def take_snapshot(token: dict, client: httpx.AsyncClient) -> dict:
    """Take an OHLCV snapshot for a token."""
    chain = token.get("chain", "")
    address = token.get("contract_address", "")

    # Find pool
    pool = await _find_pool(chain, address, client)
    if not pool:
        return {"error": "no pool found"}

    # Fetch multiple timeframes
    candles_h1 = await _fetch_ohlcv(chain, pool, "hour", 48, client)
    candles_m15 = await _fetch_ohlcv(chain, pool, "minute", 96, client)  # 24h of 15m
    candles_d1 = await _fetch_ohlcv(chain, pool, "day", 30, client)

    now = time.time()

    return {
        "timestamp": now,
        "timestamp_iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "chain": chain,
        "address": address,
        "pool": pool,
        "candles_h1": candles_h1,
        "candles_m15": candles_m15,
        "candles_d1": candles_d1,
        "candle_count": {"h1": len(candles_h1), "m15": len(candles_m15), "d1": len(candles_d1)},
        "entry_price": candles_h1[0][4] if candles_h1 else None,  # close of first candle
        "current_price": candles_h1[-1][4] if candles_h1 else None,  # close of last candle
        "token_data": {
            "symbol": token.get("symbol"),
            "score": token.get("score"),
            "fdv": token.get("fdv"),
            "volume_h24": token.get("volume_h24"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LIFECYCLE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

async def process_lifecycle(current_tokens: List[dict]) -> Dict[str, Any]:
    """
    Process the token lifecycle:

    1. For each current token: if no lifecycle file, create one with entry snapshot
    2. For each current token: if lifecycle exists, add periodic snapshot
    3. For each lifecycle file: if token not in current list, mark as exited
    """
    current_addresses = {t.get("contract_address", "") for t in current_tokens}
    now = time.time()

    # Stats
    new_entries = 0
    updated = 0
    exited = 0

    limits = httpx.Limits(max_connections=5)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20, connect=5),
        limits=limits,
        headers={"User-Agent": "Mozilla/5.0 (compatible; HermesScreener/9.0)"},
    ) as client:

        # Process current tokens
        for token in current_tokens:
            addr = token.get("contract_address", "")
            if not addr:
                continue

            lifecycle = _load_lifecycle(addr)

            if not lifecycle:
                # NEW ENTRY: create lifecycle with entry snapshot
                log.info("token_entered", symbol=token.get("symbol"), address=addr[:12])
                snapshot = await take_snapshot(token, client)

                lifecycle = {
                    "address": addr,
                    "chain": token.get("chain"),
                    "symbol": token.get("symbol"),
                    "status": "active",
                    "entry_time": now,
                    "entry_time_iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
                    "entry_score": token.get("score"),
                    "entry_fdv": token.get("fdv"),
                    "entry_price": snapshot.get("current_price"),
                    "snapshots": [snapshot],
                    "snapshot_count": 1,
                    "exit_time": None,
                    "exit_score": None,
                    "exit_price": None,
                    "price_change_pct": None,
                    "days_tracked": 0,
                }
                _save_lifecycle(addr, lifecycle)
                new_entries += 1

            elif lifecycle.get("status") == "active":
                # UPDATE: add periodic snapshot (every 4 hours)
                last_snapshot = lifecycle["snapshots"][-1] if lifecycle.get("snapshots") else {}
                last_time = last_snapshot.get("timestamp", 0)

                if now - last_time > 14400:  # 4 hours
                    snapshot = await take_snapshot(token, client)
                    lifecycle["snapshots"].append(snapshot)
                    lifecycle["snapshot_count"] = len(lifecycle["snapshots"])
                    lifecycle["current_score"] = token.get("score")
                    lifecycle["current_fdv"] = token.get("fdv")
                    lifecycle["days_tracked"] = round((now - lifecycle["entry_time"]) / 86400, 1)

                    # Calculate price change from entry
                    entry_price = lifecycle.get("entry_price")
                    current_price = snapshot.get("current_price")
                    if entry_price and current_price and entry_price > 0:
                        pct = ((current_price - entry_price) / entry_price) * 100
                        lifecycle["price_change_pct"] = round(pct, 2)

                    _save_lifecycle(addr, lifecycle)
                    updated += 1

        # Check for exits (tokens in lifecycle but not in current list)
        LIFECYCLE_DIR.mkdir(parents=True, exist_ok=True)
        for path in LIFECYCLE_DIR.glob("*_lifecycle.json"):
            try:
                lifecycle = json.load(open(path))
            except Exception:
                continue

            addr = lifecycle.get("address", "")
            if addr not in current_addresses and lifecycle.get("status") == "active":
                # EXITED: take final snapshot
                log.info("token_exited", symbol=lifecycle.get("symbol"), address=addr[:12],
                         days=lifecycle.get("days_tracked", 0))

                # Try to get final snapshot
                token_data = {
                    "contract_address": addr,
                    "chain": lifecycle.get("chain"),
                    "symbol": lifecycle.get("symbol"),
                }
                final_snapshot = await take_snapshot(token_data, client)

                lifecycle["status"] = "exited"
                lifecycle["exit_time"] = now
                lifecycle["exit_time_iso"] = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
                lifecycle["exit_score"] = lifecycle.get("current_score")
                lifecycle["exit_price"] = final_snapshot.get("current_price") or lifecycle.get("current_price")

                # Final price change
                entry_price = lifecycle.get("entry_price")
                exit_price = lifecycle.get("exit_price")
                if entry_price and exit_price and entry_price > 0:
                    lifecycle["price_change_pct"] = round(((exit_price - entry_price) / entry_price) * 100, 2)

                lifecycle["final_snapshot"] = final_snapshot
                lifecycle["snapshots"].append(final_snapshot)
                lifecycle["snapshot_count"] = len(lifecycle["snapshots"])

                _save_lifecycle(addr, lifecycle)
                exited += 1

    log.info("lifecycle_processed", new_entries=new_entries, updated=updated, exited=exited)
    return {"new_entries": new_entries, "updated": updated, "exited": exited}


# ═══════════════════════════════════════════════════════════════════════════════
# CHART GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def generate_lifecycle_chart(address: str) -> Optional[str]:
    """
    Generate an HTML chart showing the token's lifecycle from entry to exit.

    Returns path to the generated HTML file.
    """
    lifecycle = _load_lifecycle(address)
    if not lifecycle:
        return None

    snapshots = lifecycle.get("snapshots", [])
    if not snapshots:
        return None

    symbol = lifecycle.get("symbol", address[:8])
    status = lifecycle.get("status", "active")
    entry_price = lifecycle.get("entry_price")
    exit_price = lifecycle.get("exit_price") or lifecycle.get("current_price")
    price_change = lifecycle.get("price_change_pct")

    # Combine all candles across snapshots
    all_candles = []
    seen_timestamps = set()
    for snapshot in snapshots:
        for candle in snapshot.get("candles_h1", []):
            ts = candle[0]
            if ts not in seen_timestamps:
                seen_timestamps.add(ts)
                all_candles.append(candle)
    all_candles.sort(key=lambda c: c[0])

    # Build candle JSON for Lightweight Charts
    candle_json = json.dumps([{"time": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4]} for c in all_candles])
    volume_json = json.dumps([{"time": c[0], "value": c[5] or 0,
                               "color": "rgba(16,185,129,0.3)" if c[4] >= c[1] else "rgba(239,68,68,0.3)"}
                              for c in all_candles])

    # Entry/exit markers
    entry_time = lifecycle.get("entry_time")
    exit_time = lifecycle.get("exit_time")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{symbol} Lifecycle — {status.upper()}</title>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
body{{font-family:'SF Mono',monospace;background:#0a0e17;color:#e5e7eb;margin:0;padding:1rem}}
.header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem}}
h1{{font-size:1.3rem;margin:0}}.status{{padding:.2rem .6rem;border-radius:4px;font-size:.8rem;font-weight:bold}}
.active{{background:#10b98133;color:#10b981}}.exited{{background:#ef444433;color:#ef4444}}
.metrics{{display:flex;gap:2rem;margin-bottom:1rem;font-size:.85rem}}
.metric .label{{color:#9ca3af}}.metric .val{{font-weight:bold;font-size:1rem}}
.pos{{color:#10b981}}.neg{{color:#ef4444}}
#chart{{width:100%;height:450px;border:1px solid #374151;border-radius:8px}}
.footer{{margin-top:.5rem;font-size:.72rem;color:#9ca3af}}
</style></head><body>
<div class="header">
  <h1>{symbol} Lifecycle Chart</h1>
  <span class="status {status}">{status.upper()}</span>
</div>
<div class="metrics">
  <div class="metric"><span class="label">Entry Price</span><br><span class="val">${entry_price:.8f if entry_price else '—'}</span></div>
  <div class="metric"><span class="label">{'Exit' if status=='exited' else 'Current'} Price</span><br><span class="val">${exit_price:.8f if exit_price else '—'}</span></div>
  <div class="metric"><span class="label">Change</span><br><span class="val {'pos' if (price_change or 0)>0 else 'neg'}">{('+' if (price_change or 0)>0 else '') + str(price_change) + '%' if price_change is not None else '—'}</span></div>
  <div class="metric"><span class="label">Entry Score</span><br><span class="val">{lifecycle.get('entry_score', '—')}</span></div>
  <div class="metric"><span class="label">FDV</span><br><span class="val">${lifecycle.get('entry_fdv', 0):,.0f}</span></div>
  <div class="metric"><span class="label">Days Tracked</span><br><span class="val">{lifecycle.get('days_tracked', 0)}</span></div>
  <div class="metric"><span class="label">Snapshots</span><br><span class="val">{lifecycle.get('snapshot_count', 0)}</span></div>
</div>
<div id="chart"></div>
<div class="footer">
  Entry: {lifecycle.get('entry_time_iso', '—')} | {'Exit: ' + str(lifecycle.get('exit_time_iso', '—')) if status=='exited' else 'Still active'}
  | Pool: {lifecycle.get('address', '')[:12]}... | {len(all_candles)} candles
</div>
<script>
const chart = LightweightCharts.createChart(document.getElementById('chart'),{{
  layout:{{background:{{type:'solid',color:'#0a0e17'}},textColor:'#9ca3af'}},
  grid:{{vertLines:{{color:'#1f2937'}},horzLines:{{color:'#1f2937'}}}},
  crosshair:{{mode:0,vertLine:{{color:'#06b6d4',width:1,style:2}},horzLine:{{color:'#06b6d4',width:1,style:2}}}},
  rightPriceScale:{{borderColor:'#374151'}},
  timeScale:{{borderColor:'#374151',timeVisible:true}}
}});
const cs = chart.addCandlestickSeries({{
  upColor:'#10b981',downColor:'#ef4444',borderUpColor:'#10b981',borderDownColor:'#ef4444',
  wickUpColor:'#10b981',wickDownColor:'#ef4444'
}});
cs.setData({candle_json});
const vs = chart.addHistogramSeries({{
  color:'#26a69a',priceFormat:{{type:'volume'}},priceScaleId:''
}});
vs.priceScale().applyOptions({{scaleMargins:{{top:0.8,bottom:0}}}});
vs.setData({volume_json});

// Entry marker
{f'cs.createMarker({{time: {int(entry_time)}, position: "belowBar", color: "#06b6d4", shape: "arrowUp", text: "ENTRY"}});' if entry_time else ''}

// Exit marker
{f'cs.createMarker({{time: {int(exit_time)}, position: "aboveBar", color: "#ef4444", shape: "arrowDown", text: "EXIT"}});' if exit_time and status=="exited" else ''}

chart.timeScale().fitContent();
</script></body></html>"""

    output_path = LIFECYCLE_DIR / f"{address}_lifecycle_chart.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)

    log.info("lifecycle_chart_generated", symbol=symbol, path=str(output_path))
    return str(output_path)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def run_lifecycle() -> Dict[str, Any]:
    """Run the lifecycle tracking pipeline (sync wrapper)."""
    import asyncio

    tokens = _load_current_tokens()
    if not tokens:
        log.warning("no_tokens_for_lifecycle")
        return {"status": "no_tokens"}

    return asyncio.run(process_lifecycle(tokens))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Token lifecycle tracker")
    parser.add_argument("--chart", type=str, help="Generate lifecycle chart for address")
    parser.add_argument("--snapshot", action="store_true", help="Force snapshot all tokens")
    args = parser.parse_args()

    if args.chart:
        path = generate_lifecycle_chart(args.chart)
        if path:
            print(f"Chart generated: {path}")
        else:
            print(f"No lifecycle data for {args.chart}")
        return 0

    result = run_lifecycle()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
