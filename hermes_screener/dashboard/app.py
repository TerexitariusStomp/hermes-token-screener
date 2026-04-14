"""
Hermes Token Screener Dashboard — FastAPI with static HTML.

Serves live token/wallet data from SQLite + top100.json.
Uses inline HTML + HTMX for simplicity (no Jinja2 dependency issues).
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from hermes_screener.config import settings

app = FastAPI(
    title="Hermes Token Screener",
    description="Multi-source token screening & smart money tracking",
    version="9.0.0",
)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA ACCESS
# ═══════════════════════════════════════════════════════════════════════════════

def _load_top100() -> dict:
    path = settings.output_path
    if not path.exists():
        return {"tokens": [], "generated_at_iso": "Never", "total_candidates": 0}
    with open(path) as f:
        return json.load(f)


def _get_wallet_db():
    try:
        conn = sqlite3.connect(f"file:{settings.wallets_db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _fmt_usd(v):
    if v is None: return "—"
    v = float(v)
    if v >= 1e9: return f"${v/1e9:.1f}B"
    if v >= 1e6: return f"${v/1e6:.1f}M"
    if v >= 1e3: return f"${v/1e3:.1f}K"
    return f"${v:,.0f}"

def _fmt_pct(v):
    if v is None: return "—"
    return f"{'+' if v > 0 else ''}{v:.1f}%"

def _pct_cls(v):
    if v is None: return ""
    return "pos" if v > 0 else "neg" if v < 0 else ""

def _time_ago(ts):
    if not ts: return "—"
    d = time.time() - float(ts)
    if d < 60: return f"{int(d)}s"
    if d < 3600: return f"{int(d/60)}m"
    if d < 86400: return f"{int(d/3600)}h"
    return f"{int(d/86400)}d"

def _trunc(a, n=8):
    if not a or len(a) <= n*2: return a or ""
    return f"{a[:n]}...{a[-n:]}"

def _explorer(chain, addr):
    if chain in ("solana","sol"): return f"https://solscan.io/account/{addr}"
    if chain == "base": return f"https://basescan.org/address/{addr}"
    return f"https://etherscan.io/address/{addr}"

def _chain_cls(chain):
    return f"chain-{chain}" if chain in ("solana","sol","base","ethereum","bsc") else ""


# ═══════════════════════════════════════════════════════════════════════════════
# HTML RENDERING
# ═══════════════════════════════════════════════════════════════════════════════

CSS = """
:root{--bg:#0a0e17;--s:#111827;--s2:#1f2937;--b:#374151;--t:#e5e7eb;--t2:#9ca3af;
--g:#10b981;--r:#ef4444;--y:#f59e0b;--bl:#3b82f6;--p:#8b5cf6;--c:#06b6d4}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'SF Mono','Fira Code',monospace;background:var(--bg);color:var(--t)}
a{color:var(--c);text-decoration:none}a:hover{text-decoration:underline}
nav{background:var(--s);border-bottom:1px solid var(--b);padding:.75rem 1.5rem;display:flex;align-items:center;gap:2rem}
.logo{font-size:1.1rem;font-weight:bold;color:var(--c)}.logo span{color:var(--y)}
.nav{display:flex;gap:1.5rem}.nav a{color:var(--t2);font-size:.85rem}.nav a.active{color:var(--c)}
.stats{background:var(--s);border-bottom:1px solid var(--b);padding:.5rem 1.5rem;display:flex;gap:2rem;font-size:.8rem;color:var(--t2);flex-wrap:wrap}
.stats .v{color:var(--t);font-weight:bold}
.wrap{max-width:1400px;margin:0 auto;padding:1.5rem}
h1{font-size:1.3rem;margin-bottom:.25rem}.sub{color:var(--t2);font-size:.8rem;margin-bottom:1rem}
.tbl{overflow-x:auto;border:1px solid var(--b);border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{background:var(--s2);color:var(--t2);text-align:left;padding:.6rem .75rem;font-weight:600;position:sticky;top:0;white-space:nowrap}
td{padding:.5rem .75rem;border-top:1px solid var(--b);white-space:nowrap}
tr:hover td{background:var(--s2)}
.sc{font-weight:bold}.sc-h{color:var(--g)}.sc-m{color:var(--y)}.sc-l{color:var(--t2)}
.pos{color:var(--g)}.neg{color:var(--r)}
.badge{display:inline-block;padding:.1rem .4rem;border-radius:4px;font-size:.7rem;font-weight:bold}
.chain-solana,.chain-sol{background:#9945ff22;color:#9945ff}
.chain-base{background:#0052ff22;color:#0052ff}
.chain-ethereum{background:#627eea22;color:#627eea}
.chain-bsc{background:#f3ba2f22;color:#f3ba2f}
.tag{display:inline-block;padding:.1rem .35rem;border-radius:3px;font-size:.65rem;margin:.1rem}
.tag-g{background:#10b98133;color:#10b981}.tag-y{background:#f59e0b33;color:#f59e0b}.tag-r{background:#ef444433;color:#ef4444}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1rem;margin-top:1rem}
.card{background:var(--s);border:1px solid var(--b);border-radius:8px;padding:1rem}
.card h3{font-size:.9rem;color:var(--c);margin-bottom:.75rem}
.row{display:flex;justify-content:space-between;padding:.3rem 0;font-size:.82rem}
.row .l{color:var(--t2)}
.mono{font-family:inherit;font-size:.72rem}
@media(max-width:768px){.stats{gap:.5rem}nav{flex-wrap:wrap}}
"""

def _nav(active):
    return f"""<nav>
<div class="logo">HERMES <span>&#9670;</span> SCREENER</div>
<div class="nav">
  <a href="/" class="{'active' if active=='tokens' else ''}">Tokens</a>
  <a href="/wallets" class="{'active' if active=='wallets' else ''}">Smart Money</a>
  <a href="/api/top100" target="_blank">API</a>
  <a href="/health" target="_blank">Health</a>
</div></nav>"""

def _page(title, active, body):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Hermes</title><style>{CSS}</style></head>
<body>{_nav(active)}<div class="wrap">{body}</div>
<script>setTimeout(()=>location.reload(),30000)</script></body></html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index():
    data = _load_top100()
    tokens = data.get("tokens", [])

    rows = ""
    for i, t in enumerate(tokens, 1):
        score = t.get("score", 0) or 0
        sc_cls = "sc-h" if score >= 70 else "sc-m" if score >= 40 else "sc-l"
        p1h = _pct_cls(t.get("price_change_h1"))
        p6h = _pct_cls(t.get("price_change_h6"))
        tags = "".join(f'<span class="tag tag-g">{p}</span>' for p in (t.get("positives") or [])[:2])
        rows += f"""<tr>
  <td>{i}</td>
  <td><a href="/token/{t.get('contract_address','')}"><strong>{t.get('symbol','???')}</strong></a></td>
  <td><span class="badge {_chain_cls(t.get('chain',''))}">{t.get('chain','')}</span></td>
  <td class="mono"><a href="{_explorer(t.get('chain',''), t.get('contract_address',''))}" target="_blank">{_trunc(t.get('contract_address',''))}</a></td>
  <td class="sc {sc_cls}">{score:.1f}</td>
  <td>{t.get('channel_count',0)}</td>
  <td>{_fmt_usd(t.get('fdv'))}</td>
  <td>{_fmt_usd(t.get('volume_h24'))}</td>
  <td>{_fmt_usd(t.get('volume_h1'))}</td>
  <td class="{p1h}">{_fmt_pct(t.get('price_change_h1'))}</td>
  <td class="{p6h}">{_fmt_pct(t.get('price_change_h6'))}</td>
  <td>{t.get('age_hours',0):.1f}h</td>
  <td>{t.get('gmgn_smart_wallets',0)}</td>
  <td>{tags}</td>
</tr>"""

    return _page("Tokens", "tokens", f"""
<h1>Token Leaderboard</h1>
<div class="sub">Top {len(tokens)} tokens from {data.get('total_candidates',0)} candidates &middot; {data.get('generated_at_iso','')}</div>
<div class="tbl"><table>
<thead><tr><th>#</th><th>Token</th><th>Chain</th><th>Address</th><th>Score</th><th>Ch</th><th>FDV</th><th>Vol24h</th><th>Vol1h</th><th>1h</th><th>6h</th><th>Age</th><th>&#x1f9e0;</th><th>Signals</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>""")


@app.get("/wallets", response_class=HTMLResponse)
async def wallets(min_score: float = Query(0), chain: str = Query("")):
    conn = _get_wallet_db()
    if not conn:
        return _page("Smart Money", "wallets", "<h1>Smart Money Wallets</h1><p class='sub'>Wallet DB not available</p>")

    q = "SELECT * FROM tracked_wallets WHERE wallet_score >= ?"
    params = [min_score]
    if chain:
        q += " AND chain = ?"
        params.append(chain)
    q += " ORDER BY wallet_score DESC LIMIT 100"

    try:
        rows = conn.execute(q, params).fetchall()
        wallets_list = [dict(r) for r in rows]
    except Exception:
        wallets_list = []
    conn.close()

    rows_html = ""
    for i, w in enumerate(wallets_list, 1):
        score = w.get("wallet_score", 0) or 0
        sc_cls = "sc-h" if score >= 70 else "sc-m" if score >= 40 else "sc-l"
        profit = w.get("total_profit")
        profit_cls = "pos" if profit and profit > 0 else "neg" if profit and profit < 0 else ""
        tags_html = ""
        for t in (w.get("wallet_tags") or "").split(","):
            t = t.strip()
            if t: tags_html += f'<span class="tag {"tag-r" if t in("sniper","insider") else "tag-g" if t=="smart" else ""}">{t}</span>'
        if w.get("insider_flag"): tags_html += '<span class="tag tag-y">INSIDER</span>'

        rows_html += f"""<tr>
  <td>{i}</td>
  <td class="mono"><a href="/wallet/{w.get('address','')}">{_trunc(w.get('address',''))}</a></td>
  <td><span class="badge {_chain_cls(w.get('chain',''))}">{w.get('chain','')}</span></td>
  <td class="sc {sc_cls}">{score:.0f}</td>
  <td class="{profit_cls}">{_fmt_usd(profit)}</td>
  <td class="{_pct_cls(w.get('avg_roi'))}">{_fmt_pct(w.get('avg_roi'))}</td>
  <td>{(w.get('win_rate',0) or 0)*100:.0f}%</td>
  <td>{w.get('total_trades',0)}</td>
  <td>{tags_html}</td>
  <td>{_time_ago(w.get('last_active_at'))}</td>
</tr>"""

    return _page("Smart Money", "wallets", f"""
<h1>Smart Money Wallets</h1>
<div class="sub">{len(wallets_list)} wallets tracked</div>
<div class="tbl"><table>
<thead><tr><th>#</th><th>Address</th><th>Chain</th><th>Score</th><th>PnL</th><th>ROI</th><th>Win</th><th>Trades</th><th>Tags</th><th>Active</th></tr></thead>
<tbody>{rows_html}</tbody>
</table></div>""")


@app.get("/token/{address}", response_class=HTMLResponse)
async def token_detail(address: str):
    data = _load_top100()
    token = None
    for t in data.get("tokens", []):
        if t.get("contract_address", "").lower() == address.lower():
            token = t
            break

    if not token:
        return _page("Token", "tokens", f"<h1>Token Detail</h1><p class='sub'>{address}</p><div class='card'><h3>Not Found</h3><p>Not in current top100.json</p></div>")

    pos = "".join(f'<span class="tag tag-g">{p}</span>' for p in (token.get("positives") or []))
    neg = "".join(f'<span class="tag tag-r">{n}</span>' for n in (token.get("negatives") or []))

    return _page(token.get("symbol","Token"), "tokens", f"""
<h1>{token.get('symbol','???')} <span style="color:var(--t2);font-weight:normal">({token.get('name','')})</span></h1>
<div class="sub">
  <span class="badge {_chain_cls(token.get('chain',''))}">{token.get('chain','')}</span>
  <a href="{_explorer(token.get('chain',''), address)}" target="_blank">{address}</a>
</div>
<div class="grid">
  <div class="card">
    <h3>Score & Signals</h3>
    <div class="row"><span class="l">Final Score</span><span class="sc sc-h">{(token.get('score',0) or 0):.1f}</span></div>
    <div class="row"><span class="l">Channels</span><span>{token.get('channel_count',0)} ch, {token.get('mentions',0)} mentions</span></div>
    <div class="row"><span class="l">Smart Wallets</span><span>&#x1f9e0; {token.get('gmgn_smart_wallets',0)}</span></div>
    <div style="margin-top:.5rem">{pos}{neg}</div>
  </div>
  <div class="card">
    <h3>Market Data</h3>
    <div class="row"><span class="l">FDV</span><span>{_fmt_usd(token.get('fdv'))}</span></div>
    <div class="row"><span class="l">Vol 24h</span><span>{_fmt_usd(token.get('volume_h24'))}</span></div>
    <div class="row"><span class="l">Vol 1h</span><span>{_fmt_usd(token.get('volume_h1'))}</span></div>
    <div class="row"><span class="l">Age</span><span>{(token.get('age_hours',0) or 0):.1f}h</span></div>
  </div>
  <div class="card">
    <h3>Price Action</h3>
    <div class="row"><span class="l">1h</span><span class="{_pct_cls(token.get('price_change_h1'))}">{_fmt_pct(token.get('price_change_h1'))}</span></div>
    <div class="row"><span class="l">6h</span><span class="{_pct_cls(token.get('price_change_h6'))}">{_fmt_pct(token.get('price_change_h6'))}</span></div>
    <div class="row"><span class="l">24h</span><span class="{_pct_cls(token.get('price_change_h24'))}">{_fmt_pct(token.get('price_change_h24'))}</span></div>
  </div>
  <div class="card">
    <h3>Links</h3>
    <div class="row"><a href="{token.get('dex_url','')}" target="_blank">Dexscreener &rarr;</a></div>
    <div class="row"><a href="{_explorer(token.get('chain',''), address)}" target="_blank">Explorer &rarr;</a></div>
  </div>
</div>""")


@app.get("/wallet/{address}", response_class=HTMLResponse)
async def wallet_detail(address: str):
    conn = _get_wallet_db()
    if not conn:
        return _page("Wallet", "wallets", "<h1>Wallet</h1><p class='sub'>DB not available</p>")

    wallet = conn.execute("SELECT * FROM tracked_wallets WHERE address = ?", (address,)).fetchone()
    positions = conn.execute("SELECT * FROM wallet_token_entries WHERE wallet_address = ? ORDER BY profit DESC LIMIT 50", (address,)).fetchall()
    conn.close()

    w = dict(wallet) if wallet else {}
    pos_list = [dict(p) for p in positions]

    if not w:
        return _page("Wallet", "wallets", f"<h1>Wallet</h1><p class='sub'>{address}</p><div class='card'><h3>Not Found</h3></div>")

    pos_rows = ""
    for p in pos_list:
        p_cls = "pos" if p.get("profit") and p["profit"] > 0 else "neg"
        pos_rows += f"""<tr>
  <td><a href="/token/{p.get('token_address','')}">{p.get('token_symbol') or _trunc(p.get('token_address',''),8)}</a></td>
  <td class="{p_cls}">{_fmt_usd(p.get('profit'))}</td>
  <td>{_fmt_usd(p.get('realized_profit'))}</td>
  <td>{p.get('buy_tx_count',0)}</td>
  <td>{p.get('sell_tx_count',0)}</td>
  <td>{'&#10003;' if p.get('is_profitable') else '&#10007;'}</td>
  <td>{_time_ago(p.get('start_holding_at'))}</td>
</tr>"""

    return _page(f"Wallet {_trunc(address,12)}", "wallets", f"""
<h1>Wallet Detail</h1>
<div class="sub">
  <span class="badge {_chain_cls(w.get('chain',''))}">{w.get('chain','')}</span>
  <a href="{_explorer(w.get('chain','sol'), address)}" target="_blank">{address}</a>
</div>
<div class="grid">
  <div class="card">
    <h3>Performance</h3>
    <div class="row"><span class="l">Score</span><span class="sc sc-h">{(w.get('wallet_score',0) or 0):.0f}</span></div>
    <div class="row"><span class="l">Total PnL</span><span class="{'pos' if (w.get('total_profit') or 0)>0 else 'neg'}">{_fmt_usd(w.get('total_profit'))}</span></div>
    <div class="row"><span class="l">Avg ROI</span><span class="{_pct_cls(w.get('avg_roi'))}">{_fmt_pct(w.get('avg_roi'))}</span></div>
    <div class="row"><span class="l">Win Rate</span><span>{(w.get('win_rate',0) or 0)*100:.0f}%</span></div>
    <div class="row"><span class="l">Entry Timing</span><span>{(w.get('entry_timing_score',0) or 0):.0f}</span></div>
  </div>
  <div class="card">
    <h3>Activity</h3>
    <div class="row"><span class="l">Trades</span><span>{w.get('total_trades',0)}</span></div>
    <div class="row"><span class="l">Buys / Sells</span><span>{w.get('buy_count',0)} / {w.get('sell_count',0)}</span></div>
    <div class="row"><span class="l">Won</span><span>{w.get('tokens_profitable',0)} / {w.get('tokens_total',0)}</span></div>
    <div class="row"><span class="l">Pattern</span><span>{w.get('trading_pattern','—')}</span></div>
    <div class="row"><span class="l">Last Active</span><span>{_time_ago(w.get('last_active_at'))}</span></div>
  </div>
</div>
{'<div style="margin-top:1.5rem"><h2 style="font-size:1rem;margin-bottom:.75rem">Token Positions (' + str(len(pos_list)) + ')</h2><div class="tbl"><table><thead><tr><th>Token</th><th>PnL</th><th>Realized</th><th>Buy</th><th>Sell</th><th>Win</th><th>Seen</th></tr></thead><tbody>' + pos_rows + '</tbody></table></div></div>' if pos_list else ''}""")


@app.get("/health")
async def health():
    checks = {}
    for name, path in [("top100", settings.output_path), ("contracts_db", settings.db_path), ("wallets_db", settings.wallets_db_path)]:
        checks[name] = {"exists": path.exists(), "size": path.stat().st_size if path.exists() else 0}
    return {"status": "healthy", "version": "9.0.0", "checks": checks}


@app.get("/api/top100")
async def api_top100():
    return _load_top100()


@app.get("/api/wallets")
async def api_wallets(min_score: float = Query(0), limit: int = Query(50, le=200)):
    conn = _get_wallet_db()
    if not conn: return []
    rows = conn.execute("SELECT * FROM tracked_wallets WHERE wallet_score >= ? ORDER BY wallet_score DESC LIMIT ?", (min_score, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/stats")
async def api_stats():
    data = _load_top100()
    try:
        conn = _get_wallet_db()
        wc = conn.execute("SELECT COUNT(*) FROM tracked_wallets").fetchone()[0] if conn else 0
        avg = conn.execute("SELECT AVG(wallet_score) FROM tracked_wallets").fetchone()[0] if conn else 0
        if conn: conn.close()
    except: wc = avg = 0
    return {"tokens_scored": len(data.get("tokens",[])), "total_candidates": data.get("total_candidates",0), "wallets_tracked": wc, "avg_wallet_score": round(avg or 0,1), "last_generated": data.get("generated_at_iso","Never")}
