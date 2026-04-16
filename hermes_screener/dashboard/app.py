"""
Hermes Token Screener Dashboard — FastAPI with static HTML.

Serves live token/wallet data from SQLite + top100.json.
TradingView Lightweight Charts for token price charts.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from hermes_screener.config import settings

sys.path.insert(0, str(settings.hermes_home / 'scripts'))

app = FastAPI(
    title="Hermes Token Screener",
    description="Multi-source token screening & smart money tracking",
    version="9.0.0",
)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA ACCESS
# ═══════════════════════════════════════════════════════════════════════════════

def _load_top100() -> dict[str, Any]:
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
    if v is None:
        return "—"
    v = float(v)
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.1f}K"
    return f"${v:,.0f}"

def _fmt_pct(v):
    if v is None:
        return "—"
    return f"{'+' if v > 0 else ''}{v:.1f}%"

def _pct_cls(v):
    if v is None:
        return ""
    return "pos" if v > 0 else "neg" if v < 0 else ""

def _time_ago(ts):
    if not ts:
        return "—"
    d = time.time() - float(ts)
    if d < 60:
        return f"{int(d)}s"
    if d < 3600:
        return f"{int(d/60)}m"
    if d < 86400:
        return f"{int(d/3600)}h"
    return f"{int(d/86400)}d"

def _trunc(a, n=8):
    if not a or len(a) <= n*2:
        return a or ""
    return f"{a[:n]}...{a[-n:]}"

def _explorer(chain, addr):
    if chain in ("solana", "sol"):
        return f"https://solscan.io/account/{addr}"
    if chain == "base":
        return f"https://basescan.org/address/{addr}"
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
.trending{background:linear-gradient(90deg,#0a0e17,#111827);border-bottom:1px solid var(--b);padding:.6rem 1.5rem;display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;font-size:.78rem}
.trending .label{color:var(--y);font-weight:bold;white-space:nowrap}
.trending .kw{display:inline-block;padding:.2rem .5rem;border-radius:4px;background:#06b6d422;color:var(--c);cursor:default;transition:all .2s}
.trending .kw:hover{background:#06b6d444}
.trending .kw .ct{font-size:.65rem;color:var(--t2);margin-left:.3rem}
.trending .sep{color:var(--b)}
"""

CHART_CSS = """
#chart-container{width:100%;height:500px;background:var(--bg);border:1px solid var(--b);border-radius:8px;position:relative}
#chart-container .loading{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:var(--t2)}
.controls{display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap;align-items:center}
.controls button{background:var(--s2);color:var(--t);border:1px solid var(--b);padding:.35rem .75rem;border-radius:4px;cursor:pointer;font-family:inherit;font-size:.8rem}
.controls button:hover,.controls button.active{background:var(--c);color:#000;border-color:var(--c)}
.controls select{background:var(--s2);color:var(--t);border:1px solid var(--b);padding:.35rem .5rem;border-radius:4px;font-family:inherit;font-size:.8rem}
.price-info{display:flex;gap:1.5rem;margin-bottom:1rem;flex-wrap:wrap}
.price-info .item{font-size:.82rem}.price-info .item .label{color:var(--t2)}
.price-info .item .val{font-weight:bold;font-size:1rem}
.chart-footer{margin-top:.75rem;font-size:.72rem;color:var(--t2)}
"""

def _nav(active):
    return f"""<nav>
<div class="logo">HERMES <span>&#9670;</span> SCREENER</div>
<div class="nav">
  <a href="/" class="{'active' if active=='tokens' else ''}">Tokens</a>
  <a href="/wallets" class="{'active' if active=='wallets' else ''}">Smart Money</a>
  <a href="/cross/tokens" class="{'active' if active=='cross-tokens' else ''}">Tokens×Wallets</a>
  <a href="/cross/wallets" class="{'active' if active=='cross-wallets' else ''}">Wallets×Tokens</a>
  <a href="/api/top100" target="_blank">API</a>
  <a href="/health" target="_blank">Health</a>
</div></nav>"""

def _page(title, active, body, extra_css=""):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Hermes</title><style>{CSS}{extra_css}</style></head>
<body>{_nav(active)}<div class="wrap">{body}</div>
<script>setTimeout(()=>location.reload(),30000)</script></body></html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# CHART PAGE
# ═══════════════════════════════════════════════════════════════════════════════

def _chart_html(symbol, chain, address, dex_url, pair_address, current_price, fdv, vol24):
    """Generate full chart page with TradingView Lightweight Charts."""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{symbol} Chart — Hermes</title>
<style>{CSS}{CHART_CSS}</style>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
</head>
<body>
{_nav("tokens")}
<div class="wrap">
  <h1>{symbol} <span style="color:var(--t2);font-weight:normal">Chart</span></h1>
  <div class="sub">
    <span class="badge {_chain_cls(chain)}">{chain}</span>
    <a href="/token/{address}">&larr; Token Detail</a>
    &middot; <a href="{dex_url}" target="_blank">Dexscreener</a>
  </div>

  <div class="price-info">
    <div class="item"><span class="label">Price</span><br><span class="val" id="current-price">{f'${float(current_price):.8f}' if current_price else '—'}</span></div>
    <div class="item"><span class="label">FDV</span><br><span class="val">{_fmt_usd(fdv)}</span></div>
    <div class="item"><span class="label">Vol 24h</span><br><span class="val">{_fmt_usd(vol24)}</span></div>
    <div class="item"><span class="label">24h Change</span><br><span class="val" id="day-change">—</span></div>
  </div>

  <div class="controls">
    <button onclick="setTimeframe('minute', 5)" id="btn-5m">5m</button>
    <button onclick="setTimeframe('minute', 15)" id="btn-15m">15m</button>
    <button onclick="setTimeframe('hour', 1)" class="active" id="btn-1h">1H</button>
    <button onclick="setTimeframe('hour', 4)" id="btn-4h">4H</button>
    <button onclick="setTimeframe('day', 1)" id="btn-1d">1D</button>
    <select id="chart-type" onchange="setChartType(this.value)">
      <option value="candlestick">Candlestick</option>
      <option value="line">Line</option>
      <option value="area">Area</option>
    </select>
  </div>

  <div id="chart-container">
    <div class="loading">Loading chart data...</div>
  </div>
  <div class="chart-footer">
    Data from GeckoTerminal &middot; Auto-refreshes every 60s &middot;
    <span id="candle-count">0</span> candles loaded
  </div>
</div>

<script>
const CHAIN = {json.dumps(chain)};
const ADDRESS = {json.dumps(address)};
const POOL_CACHE = {{}};
let chart, candleSeries, volumeSeries, currentTf = 'hour', currentAgg = 1;
let chartType = 'candlestick';

// ── Chart Init ──
function initChart() {{
  const container = document.getElementById('chart-container');
  container.innerHTML = '';
  chart = LightweightCharts.createChart(container, {{
    width: container.clientWidth,
    height: 500,
    layout: {{ background: {{ type: 'solid', color: '#0a0e17' }}, textColor: '#9ca3af' }},
    grid: {{ vertLines: {{ color: '#1f2937' }}, horzLines: {{ color: '#1f2937' }} }},
    crosshair: {{
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: {{ color: '#06b6d4', width: 1, style: 2 }},
      horzLine: {{ color: '#06b6d4', width: 1, style: 2 }},
    }},
    rightPriceScale: {{ borderColor: '#374151' }},
    timeScale: {{ borderColor: '#374151', timeVisible: true, secondsVisible: false }},
  }});

  candleSeries = chart.addCandlestickSeries({{
    upColor: '#10b981', downColor: '#ef4444',
    borderUpColor: '#10b981', borderDownColor: '#ef4444',
    wickUpColor: '#10b981', wickDownColor: '#ef4444',
  }});

  volumeSeries = chart.addHistogramSeries({{
    color: '#26a69a',
    priceFormat: {{ type: 'volume' }},
    priceScaleId: '',
  }});
  volumeSeries.priceScale().applyOptions({{
    scaleMargins: {{ top: 0.8, bottom: 0 }},
  }});

  chart.timeScale().fitContent();
  window.addEventListener('resize', () => chart.applyOptions({{ width: container.clientWidth }}));
}}

// ── Data Fetch ──
async function fetchPoolAddress() {{
  if (POOL_CACHE[ADDRESS]) return POOL_CACHE[ADDRESS];
  try {{
    const resp = await fetch(`/api/pool/${{CHAIN}}/${{ADDRESS}}`);
    const data = await resp.json();
    POOL_CACHE[ADDRESS] = data.pool_address;
    return data.pool_address;
  }} catch {{ return null; }}
}}

async function fetchOHLCV(tf, agg) {{
  const pool = await fetchPoolAddress();
  if (!pool) return [];
  try {{
    const resp = await fetch(`/api/chart/${{CHAIN}}/${{pool}}?timeframe=${{tf}}&aggregate=${{agg}}&limit=200`);
    const data = await resp.json();
    return data.candles || [];
  }} catch {{ return []; }}
}}

// ── Render ──
async function loadChart(tf, agg) {{
  currentTf = tf; currentAgg = agg;
  document.getElementById('chart-container').innerHTML = '<div class="loading">Loading...</div>';
  initChart();

  const candles = await fetchOHLCV(tf, agg);
  if (!candles.length) {{
    document.getElementById('chart-container').innerHTML = '<div class="loading">No chart data available for this pair</div>';
    return;
  }}

  const candleData = candles.map(c => ({{ time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] }}));
  const volumeData = candles.map(c => ({{
    time: c[0], value: c[5] || 0,
    color: c[4] >= c[1] ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'
  }}));

  candleSeries.setData(candleData);
  volumeSeries.setData(volumeData);
  chart.timeScale().fitContent();

  // Update 24h change
  if (candleData.length > 1) {{
    const first = candleData[0].open;
    const last = candleData[candleData.length - 1].close;
    const change = ((last - first) / first * 100).toFixed(2);
    const el = document.getElementById('day-change');
    el.textContent = (change > 0 ? '+' : '') + change + '%';
    el.className = 'val ' + (change > 0 ? 'pos' : 'neg');
  }}
  document.getElementById('candle-count').textContent = candleData.length;
}}

// ── Controls ──
function setTimeframe(tf, agg) {{
  document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
  document.getElementById(`btn-${{agg}}${{tf[0]}}`).classList.add('active');
  loadChart(tf, agg);
}}

function setChartType(type) {{
  chartType = type;
  // Remove existing series and re-add
  chart.removeSeries(candleSeries);
  if (type === 'candlestick') {{
    candleSeries = chart.addCandlestickSeries({{
      upColor: '#10b981', downColor: '#ef4444',
      borderUpColor: '#10b981', borderDownColor: '#ef4444',
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    }});
  }} else if (type === 'line') {{
    candleSeries = chart.addLineSeries({{ color: '#06b6d4', lineWidth: 2 }});
  }} else {{
    candleSeries = chart.addAreaSeries({{
      lineColor: '#06b6d4', lineWidth: 2,
      topColor: 'rgba(6,182,212,0.3)', bottomColor: 'rgba(6,182,212,0)',
    }});
  }}
  loadChart(currentTf, currentAgg);
}}

// ── Init ──
initChart();
loadChart('hour', 1);
</script>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index():
    data = _load_top100()
    tokens = data.get("tokens", [])

    # Load trending keywords
    tk_path = settings.output_path.parent / "trending_keywords.json"
    trending_html = ""
    if tk_path.exists():
        try:
            tk_data = json.loads(tk_path.read_text())
            kws = tk_data.get("keywords", [])[:12]
            if kws:
                kw_items = "".join(
                    f'<span class="kw">{kw["keyword"]}<span class="ct">{kw["count"]}</span></span>'
                    for kw in kws
                )
                trending_html = f'<div class="trending"><span class="label">&#128293; TRENDING</span>{kw_items}</div>'
        except Exception:
            pass

    rows = ""
    for i, t in enumerate(tokens, 1):
        score = t.get("score", 0) or 0
        sc_cls = "sc-h" if score >= 70 else "sc-m" if score >= 40 else "sc-l"
        p1h = _pct_cls(t.get("price_change_h1"))
        p6h = _pct_cls(t.get("price_change_h6"))
        tags = "".join(f'<span class="tag tag-g">{p}</span>' for p in (t.get("positives") or [])[:2])
        addr = t.get('contract_address','')
        rows += f"""<tr>
  <td>{i}</td>
  <td><a href="/token/{addr}"><strong>{t.get('symbol','???')}</strong></a></td>
  <td><span class="badge {_chain_cls(t.get('chain',''))}">{t.get('chain','')}</span></td>
  <td class="mono"><a href="{_explorer(t.get('chain',''), addr)}" target="_blank">{_trunc(addr)}</a></td>
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
{trending_html}
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
    params: list[float | str] = [min_score]
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
            if t:
                tag_cls = "tag-r" if t in ("sniper", "insider") else "tag-g" if t == "smart" else ""
                tags_html += f'<span class="tag {tag_cls}">{t}</span>'
        if w.get("insider_flag"):
            tags_html += '<span class="tag tag-y">INSIDER</span>'

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
  &middot; <a href="/token/{address}/chart" style="font-weight:bold;color:var(--y)">&#9654; Live Chart</a>
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
    <div class="row"><a href="/token/{address}/chart" style="font-weight:bold;color:var(--y)">&#9654; Live Chart</a></div>
    <div class="row"><a href="{token.get('dex_url','')}" target="_blank">Dexscreener &rarr;</a></div>
    <div class="row"><a href="{_explorer(token.get('chain',''), address)}" target="_blank">Explorer &rarr;</a></div>
  </div>
</div>""")


@app.get("/token/{address}/chart", response_class=HTMLResponse)
async def token_chart(address: str):
    """Full-page TradingView chart for a token."""
    data = _load_top100()
    token = None
    for t in data.get("tokens", []):
        if t.get("contract_address", "").lower() == address.lower():
            token = t
            break

    if not token:
        return _page("Chart", "tokens", "<h1>Chart</h1><p class='sub'>Token not found</p>")

    return HTMLResponse(_chart_html(
        symbol=token.get("symbol", "???"),
        chain=token.get("chain", "solana"),
        address=address,
        dex_url=token.get("dex_url", ""),
        pair_address=token.get("pair_address", ""),
        current_price=token.get("fdv"),
        fdv=token.get("fdv"),
        vol24=token.get("volume_h24"),
    ))


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
    <div class="row"><span class="l">Last Active</span><span>{_time_ago(w.get('last_active_at'))}</span></div>
  </div>
</div>
{'<div style="margin-top:1.5rem"><h2 style="font-size:1rem;margin-bottom:.75rem">Token Positions (' + str(len(pos_list)) + ')</h2><div class="tbl"><table><thead><tr><th>Token</th><th>PnL</th><th>Realized</th><th>Buy</th><th>Sell</th><th>Win</th><th>Seen</th></tr></thead><tbody>' + pos_rows + '</tbody></table></div></div>' if pos_list else ''}""")


# ═══════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

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
    if not conn:
        return []
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
        if conn:
            conn.close()
    except Exception:
        wc = avg = 0
    return {"tokens_scored": len(data.get("tokens",[])), "total_candidates": data.get("total_candidates",0), "wallets_tracked": wc, "avg_wallet_score": round(avg or 0,1), "last_generated": data.get("generated_at_iso","Never")}


@app.get("/api/trending_keywords")
async def api_trending_keywords():
    path = settings.output_path.parent / "trending_keywords.json"
    if not path.exists():
        return {"keywords": [], "generated_at": "Never"}
    return json.loads(path.read_text())


# ═══════════════════════════════════════════════════════════════════════════════
# CHART API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

# Chain ID mapping for GeckoTerminal
_GT_NETWORKS = {
    "solana": "solana", "sol": "solana",
    "ethereum": "eth", "eth": "eth",
    "base": "base",
    "binance": "bsc", "bsc": "bsc", "binance-smart-chain": "bsc",
}


@app.get("/api/pool/{chain}/{address}")
async def api_find_pool(chain: str, address: str):
    """Find the top liquidity pool for a token on GeckoTerminal."""
    net = _GT_NETWORKS.get(chain.lower(), "solana")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.geckoterminal.com/api/v2/networks/{net}/tokens/{address}/pools",
                params={"sort": "h24_tx_count_desc", "page": "1"},
            )
            if resp.status_code != 200:
                return {"pool_address": None, "error": f"status {resp.status_code}"}

            pools = resp.json().get("data", [])
            if not pools:
                return {"pool_address": None, "error": "no pools found"}

            # Return pool address (strip network prefix if present)
            pool_id = pools[0]["id"]
            pool_addr = pool_id.split("_")[-1] if "_" in pool_id else pool_id

            return {
                "pool_address": pool_addr,
                "pool_name": pools[0].get("attributes", {}).get("name", ""),
                "dex": pools[0].get("attributes", {}).get("dex", {}).get("name", ""),
                "reserve_usd": pools[0].get("attributes", {}).get("reserve_in_usd"),
            }
    except Exception as e:
        return {"pool_address": None, "error": str(e)}


@app.get("/api/chart/{chain}/{pool_address}")
async def api_chart_ohlcv(
    chain: str,
    pool_address: str,
    timeframe: str = Query("hour", pattern="^(minute|hour|day)$"),
    aggregate: int = Query(1, ge=1, le=24),
    limit: int = Query(200, ge=1, le=1000),
):
    """Fetch OHLCV candle data from GeckoTerminal.

    Returns candles as [[timestamp, open, high, low, close, volume], ...]
    Compatible with TradingView Lightweight Charts.
    """
    net = _GT_NETWORKS.get(chain.lower(), "solana")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.geckoterminal.com/api/v2/networks/{net}/pools/{pool_address}/ohlcv/{timeframe}",
                params={"aggregate": str(aggregate), "limit": str(limit)},
            )
            if resp.status_code != 200:
                return {"candles": [], "count": 0, "timeframe": timeframe, "aggregate": aggregate, "error": f"status {resp.status_code}"}

            candles = resp.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])
            return {
                "candles": candles,
                "count": len(candles),
                "timeframe": timeframe,
                "aggregate": aggregate,
            }
    except Exception as e:
        return {"candles": [], "count": 0, "timeframe": timeframe, "aggregate": aggregate, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-REFERENCE: TOKENS × WALLETS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_top_wallets(limit: int = 200) -> list[dict]:
    """Get top wallets by score from wallet DB."""
    conn = _get_wallet_db()
    if not conn:
        return []
    try:
        rows = conn.execute(
            "SELECT address, chain, wallet_score FROM tracked_wallets "
            "WHERE wallet_score > 0 ORDER BY wallet_score DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _get_wallet_token_holdings(wallet_address: str) -> list[str]:
    """Get token addresses held by a wallet."""
    conn = _get_wallet_db()
    if not conn:
        return []
    try:
        rows = conn.execute(
            "SELECT DISTINCT token_address FROM wallet_token_entries "
            "WHERE wallet_address = ? AND token_address IS NOT NULL",
            (wallet_address,)
        ).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []
    finally:
        conn.close()


def _cross_reference_tokens_by_wallets() -> list[dict]:
    """
    Rank tokens by how many top wallets hold them.

    Returns tokens sorted by wallet_count DESC, then by token score.
    """
    # Load top tokens
    data = _load_top100()
    tokens = data.get("tokens", [])
    if not tokens:
        return []

    # Get top wallets
    top_wallets = _get_top_wallets(200)
    if not top_wallets:
        return tokens  # Fallback: return tokens sorted by score

    # For each top wallet, get their token holdings
    wallet_holdings: dict[str, set[str]] = {}  # token_address -> set of wallet addresses
    for w in top_wallets:
        addr = w["address"]
        held_tokens = _get_wallet_token_holdings(addr)
        for token_addr in held_tokens:
            if token_addr not in wallet_holdings:
                wallet_holdings[token_addr] = set()
            wallet_holdings[token_addr].add(addr)

    # Annotate tokens with wallet_count
    for t in tokens:
        t_addr = t.get("contract_address", "")
        t["wallet_count"] = len(wallet_holdings.get(t_addr, set()))
        t["holding_wallets"] = list(wallet_holdings.get(t_addr, set()))[:10]

    # Sort by wallet_count DESC, then score DESC
    tokens.sort(key=lambda t: (t.get("wallet_count", 0), t.get("score", 0)), reverse=True)
    return tokens  # type: ignore[return-value]


def _cross_reference_wallets_by_tokens() -> list[dict]:
    """
    Rank wallets by how many top tokens they hold.

    Returns wallets sorted by top_token_count DESC, then by wallet score.
    """
    # Load top tokens
    data = _load_top100()
    tokens = data.get("tokens", [])
    top_token_addrs = {t.get("contract_address", "") for t in tokens if t.get("contract_address")}

    if not top_token_addrs:
        return []

    # Get top wallets
    top_wallets = _get_top_wallets(500)
    if not top_wallets:
        return []

    # For each wallet, count how many top tokens they hold
    wallet_results = []
    for w in top_wallets:
        addr = w["address"]
        held_tokens = _get_wallet_token_holdings(addr)
        held_set = set(held_tokens)
        top_token_overlap = held_set & top_token_addrs

        # Get symbols for held top tokens
        held_symbols = []
        for t in tokens:
            if t.get("contract_address") in top_token_overlap:
                held_symbols.append(t.get("symbol", "?"))

        wallet_results.append({
            "address": addr,
            "chain": w.get("chain", ""),
            "wallet_score": w.get("wallet_score", 0),
            "top_token_count": len(top_token_overlap),
            "top_tokens": held_symbols[:10],
        })

    # Sort by top_token_count DESC, then wallet_score DESC
    wallet_results.sort(key=lambda w: (w["top_token_count"], w["wallet_score"]), reverse=True)
    return wallet_results


@app.get("/cross/tokens", response_class=HTMLResponse)
async def cross_tokens():
    """Tokens ranked by how many top wallets hold them."""
    tokens = _cross_reference_tokens_by_wallets()

    rows = ""
    for i, t in enumerate(tokens[:100], 1):
        score = t.get("score", 0) or 0
        sc_cls = "sc-h" if score >= 70 else "sc-m" if score >= 40 else "sc-l"
        wc = t.get("wallet_count", 0)
        wc_cls = "sc-h" if wc >= 10 else "sc-m" if wc >= 5 else "sc-l"
        addr = t.get("contract_address", "")
        holding_wallets = t.get("holding_wallets", [])
        wallet_links = ", ".join(
            f'<a href="/wallet/{w}">{_trunc(w, 4)}</a>' for w in holding_wallets[:5]
        )

        rows += f"""<tr>
  <td>{i}</td>
  <td><a href="/token/{addr}"><strong>{t.get('symbol','???')}</strong></a></td>
  <td><span class="badge {_chain_cls(t.get('chain',''))}">{t.get('chain','')}</span></td>
  <td class="mono"><a href="{_explorer(t.get('chain',''), addr)}" target="_blank">{_trunc(addr)}</a></td>
  <td class="sc {sc_cls}">{score:.1f}</td>
  <td class="sc {wc_cls}">{wc}</td>
  <td>{_fmt_usd(t.get('fdv'))}</td>
  <td>{_fmt_usd(t.get('volume_h24'))}</td>
  <td class="mono" style="font-size:.7rem;max-width:300px;overflow:hidden;text-overflow:ellipsis">{wallet_links}</td>
</tr>"""

    return _page("Tokens × Wallets", "cross-tokens", f"""
<h1>Tokens Ranked by Wallet Count</h1>
<div class="sub">Top tokens sorted by how many smart money wallets hold them &middot; {len(tokens)} tokens analyzed</div>
<div class="tbl"><table>
<thead><tr><th>#</th><th>Token</th><th>Chain</th><th>Address</th><th>Score</th><th>🧬 Wallets</th><th>FDV</th><th>Vol24h</th><th>Top Holders</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>""")


@app.get("/cross/wallets", response_class=HTMLResponse)
async def cross_wallets():
    """Wallets ranked by how many top tokens they hold."""
    wallets = _cross_reference_wallets_by_tokens()

    rows = ""
    for i, w in enumerate(wallets[:100], 1):
        score = w.get("wallet_score", 0) or 0
        sc_cls = "sc-h" if score >= 70 else "sc-m" if score >= 40 else "sc-l"
        tc = w.get("top_token_count", 0)
        tc_cls = "sc-h" if tc >= 10 else "sc-m" if tc >= 5 else "sc-l"
        addr = w.get("address", "")
        top_tokens = w.get("top_tokens", [])
        token_badges = " ".join(f'<span class="tag tag-g">{t}</span>' for t in top_tokens[:8])

        rows += f"""<tr>
  <td>{i}</td>
  <td class="mono"><a href="/wallet/{addr}">{_trunc(addr)}</a></td>
  <td><span class="badge {_chain_cls(w.get('chain',''))}">{w.get('chain','')}</span></td>
  <td class="sc {sc_cls}">{score:.0f}</td>
  <td class="sc {tc_cls}">{tc}</td>
  <td>{token_badges}</td>
</tr>"""

    return _page("Wallets × Tokens", "cross-wallets", f"""
<h1>Wallets Ranked by Top Token Count</h1>
<div class="sub">Smart money wallets sorted by how many top-100 tokens they hold &middot; {len(wallets)} wallets analyzed</div>
<div class="tbl"><table>
<thead><tr><th>#</th><th>Wallet</th><th>Chain</th><th>Score</th><th>🧬 Top Tokens</th><th>Held Tokens</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>""")


@app.get("/api/cross/tokens")
async def api_cross_tokens():
    """API: Tokens ranked by wallet count."""
    return _cross_reference_tokens_by_wallets()


@app.get("/api/cross/wallets")
async def api_cross_wallets():
    """API: Wallets ranked by top token count."""
    return _cross_reference_wallets_by_tokens()
