# Hermes Token Screener

Autonomous smart-money tracking system that discovers, enriches, and ranks tokens and wallets across Telegram call channels and DEX platforms.

## Architecture

<svg viewBox="0 0 1200 920" width="100%">
        <defs>
          <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill="#64748b"/>
          </marker>
          <marker id="arrowrose" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill="#fb7185"/>
          </marker>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" stroke-width="0.5"/>
          </pattern>
        </defs>

        <!-- Background -->
        <rect width="100%" height="100%" fill="url(#grid)"/>

        <!-- =================================================================
             ARROWS (drawn first for z-order behind components)
             ================================================================= -->

        <!-- Telegram → telegram_scraper -->
        <line x1="148" y1="105" x2="198" y2="145" stroke="#34d399" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- Dexscreener boosted/profiles → token_discovery -->
        <line x1="148" y1="228" x2="198" y2="180" stroke="#34d399" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- telegram_scraper → central_contracts -->
        <line x1="328" y1="160" x2="378" y2="318" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#arrowhead)"/>
        <text x="338" y="235" fill="#94a3b8" font-size="7" transform="rotate(-50,338,235)">contracts</text>

        <!-- token_discovery → central_contracts -->
        <line x1="328" y1="180" x2="378" y2="300" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- central_contracts → token_enricher -->
        <line x1="508" y1="328" x2="558" y2="328" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#arrowhead)"/>
        <text x="533" y="320" fill="#94a3b8" font-size="7" text-anchor="middle">tokens</text>

        <!-- token_enricher → top100.json -->
        <line x1="708" y1="328" x2="758" y2="328" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#arrowhead)"/>
        <text x="733" y="320" fill="#94a3b8" font-size="7" text-anchor="middle">scored</text>

        <!-- top100 → wallet_tracker -->
        <line x1="823" y1="358" x2="823" y2="448" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#arrowhead)"/>
        <text x="838" y="405" fill="#94a3b8" font-size="7">holders</text>

        <!-- wallet_tracker → wallet_tracker.db -->
        <line x1="823" y1="528" x2="823" y2="598" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- wallet_tracker.db → cross_scoring -->
        <line x1="893" y1="628" x2="958" y2="628" stroke="#34d399" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- top100 → cross_scoring (feedback loop) -->
        <path d="M 823 298 Q 920 298 920 400 L 920 558 Q 920 588 958 588" fill="none" stroke="#fb923c" stroke-width="1.5" stroke-dasharray="5,5" marker-end="url(#arrowhead)"/>
        <text x="930" y="430" fill="#fb923c" font-size="7">smart money</text>
        <text x="930" y="442" fill="#fb923c" font-size="7">feedback</text>

        <!-- cross_scoring → social_enhancement -->
        <line x1="1058" y1="628" x2="1108" y2="628" stroke="#34d399" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- top100 → social_enhancement -->
        <line x1="823" y1="358" x2="1058" y2="598" stroke="#fb923c" stroke-width="1.5" stroke-dasharray="5,5" marker-end="url(#arrowhead)"/>

        <!-- social_enhancement → website_intelligence (down) -->
        <line x1="883" y1="728" x2="883" y2="768" stroke="#22d3ee" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- top100 → ai_trading_brain -->
        <line x1="823" y1="298" x2="823" y2="208" stroke="#fb7185" stroke-width="1.5" stroke-dasharray="5,5" marker-end="url(#arrowrose)"/>

        <!-- ai_trading_brain → trade_monitor -->
        <line x1="753" y1="178" x2="698" y2="178" stroke="#fb7185" stroke-width="1.5" stroke-dasharray="5,5" marker-end="url(#arrowrose)"/>

        <!-- top100 → copytrade_monitor -->
        <line x1="893" y1="328" x2="958" y2="328" stroke="#34d399" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- wallet_tracker.db → copytrade_monitor -->
        <line x1="893" y1="628" x2="1023" y2="358" stroke="#34d399" stroke-width="1.5" stroke-dasharray="5,5" marker-end="url(#arrowhead)"/>

        <!-- top100 → token_lifecycle -->
        <line x1="758" y1="358" x2="758" y2="448" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#arrowhead)"/>

        <!-- All → Dashboard -->
        <line x1="458" y1="438" x2="458" y2="498" stroke="#22d3ee" stroke-width="1.5" marker-end="url(#arrowhead)"/>
        <line x1="758" y1="488" x2="558" y2="548" stroke="#22d3ee" stroke-width="1" stroke-dasharray="4,4" marker-end="url(#arrowhead)"/>
        <line x1="823" y1="658" x2="558" y2="568" stroke="#22d3ee" stroke-width="1" stroke-dasharray="4,4" marker-end="url(#arrowhead)"/>

        <!-- Cron orchestrator arrows -->
        <line x1="150" y1="848" x2="263" y2="160" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <line x1="150" y1="848" x2="263" y2="190" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <line x1="150" y1="848" x2="633" y2="328" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <line x1="150" y1="848" x2="823" y2="478" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <line x1="150" y1="848" x2="1023" y2="328" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <line x1="150" y1="848" x2="883" y2="768" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <line x1="150" y1="848" x2="508" y2="528" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <line x1="150" y1="848" x2="753" y2="178" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <line x1="150" y1="848" x2="633" y2="178" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>

        <!-- LLM arrows -->
        <line x1="743" y1="798" x2="798" y2="798" stroke="#fb7185" stroke-width="1" stroke-dasharray="4,4" marker-end="url(#arrowrose)"/>
        <text x="770" y="790" fill="#fb7185" font-size="7" text-anchor="middle">analysis</text>

        <line x1="743" y1="828" x2="798" y2="828" stroke="#fb7185" stroke-width="1" stroke-dasharray="4,4" marker-end="url(#arrowrose)"/>
        <text x="770" y="820" fill="#fb7185" font-size="7" text-anchor="middle">decisions</text>

        <!-- Website intel → LLM -->
        <line x1="883" y1="828" x2="883" y2="858" stroke="#fb7185" stroke-width="1" stroke-dasharray="4,4" marker-end="url(#arrowrose)"/>

        <!-- =================================================================
             EXTERNAL DATA SOURCES (left column)
             ================================================================= -->

        <!-- Telegram -->
        <rect x="20" y="70" width="128" height="50" rx="6" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1.5"/>
        <text x="84" y="90" fill="white" font-size="11" font-weight="600" text-anchor="middle">Telegram</text>
        <text x="84" y="106" fill="#94a3b8" font-size="9" text-anchor="middle">62 call channels</text>

        <!-- Dexscreener -->
        <rect x="20" y="190" width="128" height="60" rx="6" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1.5"/>
        <text x="84" y="210" fill="white" font-size="11" font-weight="600" text-anchor="middle">Dexscreener</text>
        <text x="84" y="226" fill="#94a3b8" font-size="8" text-anchor="middle">Boosted + Profiles</text>
        <text x="84" y="238" fill="#94a3b8" font-size="8" text-anchor="middle">1 req/s rate limit</text>

        <!-- 12 Enrichment APIs box -->
        <rect x="380" y="80" width="256" height="170" rx="12" fill="rgba(251, 191, 36, 0.05)" stroke="#fbbf24" stroke-width="1" stroke-dasharray="8,4"/>
        <text x="390" y="96" fill="#fbbf24" font-size="9" font-weight="600">Enrichment APIs (13 Layers)</text>

        <rect x="390" y="106" width="110" height="28" rx="4" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="445" y="124" fill="#94a3b8" font-size="8" text-anchor="middle">GoPlus v2 [EVM]</text>

        <rect x="510" y="106" width="110" height="28" rx="4" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="565" y="124" fill="#94a3b8" font-size="8" text-anchor="middle">RugCheck [SOL]</text>

        <rect x="390" y="140" width="110" height="28" rx="4" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="445" y="158" fill="#94a3b8" font-size="8" text-anchor="middle">Etherscan V2</text>

        <rect x="510" y="140" width="110" height="28" rx="4" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="565" y="158" fill="#94a3b8" font-size="8" text-anchor="middle">De.Fi</text>

        <rect x="390" y="174" width="110" height="28" rx="4" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="445" y="192" fill="#94a3b8" font-size="8" text-anchor="middle">CoinGecko</text>

        <rect x="510" y="174" width="110" height="28" rx="4" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="565" y="192" fill="#94a3b8" font-size="8" text-anchor="middle">GMGN CLI</text>

        <rect x="390" y="208" width="110" height="28" rx="4" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="445" y="226" fill="#94a3b8" font-size="8" text-anchor="middle">Zerion</text>

        <rect x="510" y="208" width="110" height="28" rx="4" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="565" y="226" fill="#94a3b8" font-size="8" text-anchor="middle">CoinStats MCP</text>

        <rect x="390" y="238" width="110" height="4" rx="2" fill="rgba(30, 41, 59, 0.3)"/>
        <text x="445" y="236" fill="#94a3b8" font-size="7" text-anchor="middle">+Surf · +Mobula L12 · +Derived</text>

        <!-- =================================================================
             DISCOVERY LAYER
             ================================================================= -->

        <!-- telegram_scraper.py -->
        <rect x="200" y="130" width="128" height="50" rx="6" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1.5"/>
        <text x="264" y="150" fill="white" font-size="10" font-weight="600" text-anchor="middle">telegram_scraper</text>
        <text x="264" y="166" fill="#94a3b8" font-size="8" text-anchor="middle">*/10 min · ~30s</text>

        <!-- token_discovery.py -->
        <rect x="200" y="160" width="128" height="50" rx="6" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1.5"/>
        <text x="264" y="175" fill="white" font-size="10" font-weight="600" text-anchor="middle">token_discovery</text>
        <text x="264" y="195" fill="#94a3b8" font-size="8" text-anchor="middle">*/30 min · ~2s</text>

        <!-- central_contracts.db -->
        <rect x="380" y="280" width="128" height="78" rx="6" fill="rgba(76, 29, 149, 0.4)" stroke="#a78bfa" stroke-width="1.5"/>
        <text x="444" y="300" fill="white" font-size="10" font-weight="600" text-anchor="middle">central_contracts</text>
        <text x="444" y="316" fill="#94a3b8" font-size="9" text-anchor="middle">.db</text>
        <text x="444" y="334" fill="#a78bfa" font-size="7" text-anchor="middle">telegram_unique (505+)</text>
        <text x="444" y="346" fill="#a78bfa" font-size="7" text-anchor="middle">telegram_calls (794+)</text>

        <!-- =================================================================
             ENRICHMENT + SCORING
             ================================================================= -->

        <!-- token_enricher.py -->
        <rect x="560" y="280" width="148" height="78" rx="6" fill="rgba(120, 53, 15, 0.3)" stroke="#fbbf24" stroke-width="1.5"/>
        <text x="634" y="296" fill="white" font-size="10" font-weight="600" text-anchor="middle">token_enricher</text>
        <text x="634" y="312" fill="#94a3b8" font-size="8" text-anchor="middle">13 layers · :10 hourly</text>
        <text x="634" y="328" fill="#fbbf24" font-size="7" text-anchor="middle">async: ~8min → ~2min</text>
        <text x="634" y="342" fill="#fbbf24" font-size="7" text-anchor="middle">L0 required · L1-12 bypass</text>
        <text x="634" y="356" fill="#fbbf24" font-size="7" text-anchor="middle">Mobula L12 organic ratio</text>

        <!-- top100.json -->
        <rect x="760" y="280" width="128" height="58" rx="6" fill="rgba(76, 29, 149, 0.4)" stroke="#a78bfa" stroke-width="1.5"/>
        <text x="824" y="296" fill="white" font-size="10" font-weight="600" text-anchor="middle">top100.json</text>
        <text x="824" y="312" fill="#94a3b8" font-size="8" text-anchor="middle">Scored 0-100</text>
        <text x="824" y="326" fill="#a78bfa" font-size="7" text-anchor="middle">social+fresh+FDV+vol+txn+momentum</text>

        <!-- =================================================================
             WALLET + CROSS-SCORING LAYER
             ================================================================= -->

        <!-- wallet_tracker.py -->
        <rect x="760" y="450" width="128" height="78" rx="6" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1.5"/>
        <text x="824" y="468" fill="white" font-size="10" font-weight="600" text-anchor="middle">wallet_tracker</text>
        <text x="824" y="484" fill="#94a3b8" font-size="8" text-anchor="middle">500/token · :15 hourly</text>
        <text x="824" y="498" fill="#34d399" font-size="7" text-anchor="middle">5 sort × 100 (profitable)</text>
        <text x="824" y="512" fill="#34d399" font-size="7" text-anchor="middle">--sequential (GMGN rate)</text>
        <text x="824" y="526" fill="#34d399" font-size="7" text-anchor="middle">Score v3: PNL+WR+ROI+timing</text>

        <!-- wallet_tracker.db -->
        <rect x="760" y="600" width="128" height="58" rx="6" fill="rgba(76, 29, 149, 0.4)" stroke="#a78bfa" stroke-width="1.5"/>
        <text x="824" y="618" fill="white" font-size="10" font-weight="600" text-anchor="middle">wallet_tracker</text>
        <text x="824" y="632" fill="#94a3b8" font-size="9" text-anchor="middle">.db</text>
        <text x="824" y="648" fill="#a78bfa" font-size="7" text-anchor="middle">top 1000 by score</text>

        <!-- cross_scoring.py -->
        <rect x="960" y="590" width="98" height="58" rx="6" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1.5"/>
        <text x="1009" y="610" fill="white" font-size="10" font-weight="600" text-anchor="middle">cross_scoring</text>
        <text x="1009" y="626" fill="#94a3b8" font-size="8" text-anchor="middle">:20 hourly</text>
        <text x="1009" y="640" fill="#34d399" font-size="7" text-anchor="middle">70 smart+30 enrich</text>

        <!-- social_enhancement.py -->
        <rect x="1060" y="590" width="118" height="78" rx="6" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1.5"/>
        <text x="1119" y="610" fill="white" font-size="10" font-weight="600" text-anchor="middle">social_enhance</text>
        <text x="1119" y="626" fill="#94a3b8" font-size="8" text-anchor="middle">:25 hourly</text>
        <text x="1119" y="642" fill="#34d399" font-size="7" text-anchor="middle">Twitter+TG+website</text>
        <text x="1119" y="656" fill="#34d399" font-size="7" text-anchor="middle">70 smart+20 social</text>
        <text x="1119" y="666" fill="#34d399" font-size="7" text-anchor="middle">+10 website</text>

        <!-- =================================================================
             INTELLIGENCE + ACTION LAYER
             ================================================================= -->

        <!-- ai_trading_brain.py -->
        <rect x="760" y="150" width="128" height="58" rx="6" fill="rgba(136, 19, 55, 0.4)" stroke="#fb7185" stroke-width="1.5"/>
        <text x="824" y="168" fill="white" font-size="10" font-weight="600" text-anchor="middle">ai_trading_brain</text>
        <text x="824" y="184" fill="#94a3b8" font-size="8" text-anchor="middle">Bonsai-8B :8082</text>
        <text x="824" y="200" fill="#fb7185" font-size="7" text-anchor="middle">buy/hold/sell + confidence</text>

        <!-- trade_monitor.py -->
        <rect x="560" y="150" width="148" height="58" rx="6" fill="rgba(136, 19, 55, 0.4)" stroke="#fb7185" stroke-width="1.5"/>
        <text x="634" y="168" fill="white" font-size="10" font-weight="600" text-anchor="middle">trade_monitor</text>
        <text x="634" y="184" fill="#94a3b8" font-size="8" text-anchor="middle">EVERY MINUTE</text>
        <text x="634" y="200" fill="#fb7185" font-size="7" text-anchor="middle">TP 100% · SL 15% · decay</text>

        <!-- copytrade_monitor.py -->
        <rect x="960" y="280" width="118" height="58" rx="6" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1.5"/>
        <text x="1019" y="300" fill="white" font-size="10" font-weight="600" text-anchor="middle">copytrade_monitor</text>
        <text x="1019" y="316" fill="#94a3b8" font-size="8" text-anchor="middle">Ankr polling</text>
        <text x="1019" y="330" fill="#34d399" font-size="7" text-anchor="middle">smart wallet → new buys</text>

        <!-- token_lifecycle.py -->
        <rect x="760" y="450" width="128" height="38" rx="6" fill="rgba(120, 53, 15, 0.3)" stroke="#fbbf24" stroke-width="1.5"/>
        <text x="824" y="474" fill="white" font-size="10" font-weight="600" text-anchor="middle">token_lifecycle</text>
        <text x="824" y="482" fill="#94a3b8" font-size="7" text-anchor="middle">PNG chart snapshots</text>

        <!-- website_intelligence.py -->
        <rect x="800" y="770" width="166" height="58" rx="6" fill="rgba(8, 51, 68, 0.4)" stroke="#22d3ee" stroke-width="1.5"/>
        <text x="883" y="790" fill="white" font-size="10" font-weight="600" text-anchor="middle">website_intelligence</text>
        <text x="883" y="806" fill="#94a3b8" font-size="8" text-anchor="middle">Bonsai-8B + algo fallback</text>
        <text x="883" y="820" fill="#22d3ee" font-size="7" text-anchor="middle">blog+complexity+trend+traffic</text>

        <!-- Bonsai-8B LLM -->
        <rect x="800" y="840" width="166" height="50" rx="6" fill="rgba(136, 19, 55, 0.4)" stroke="#fb7185" stroke-width="1.5"/>
        <text x="883" y="860" fill="white" font-size="10" font-weight="600" text-anchor="middle">Bonsai-8B</text>
        <text x="883" y="876" fill="#94a3b8" font-size="8" text-anchor="middle">localhost:8082 · GGUF Q1</text>

        <!-- =================================================================
             DASHBOARD + INFRASTRUCTURE
             ================================================================= -->

        <!-- FastAPI Dashboard -->
        <rect x="410" y="500" width="148" height="78" rx="6" fill="rgba(8, 51, 68, 0.4)" stroke="#22d3ee" stroke-width="1.5"/>
        <text x="484" y="518" fill="white" font-size="10" font-weight="600" text-anchor="middle">FastAPI Dashboard</text>
        <text x="484" y="534" fill="#94a3b8" font-size="8" text-anchor="middle">:8080 · Docker</text>
        <text x="484" y="548" fill="#22d3ee" font-size="7" text-anchor="middle">/token/{addr}/chart</text>
        <text x="484" y="560" fill="#22d3ee" font-size="7" text-anchor="middle">TradingView Lightweight</text>
        <text x="484" y="572" fill="#22d3ee" font-size="7" text-anchor="middle">GeckoTerminal OHLCV</text>

        <!-- smart_money_research.py -->
        <rect x="410" y="590" width="148" height="48" rx="6" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1.5"/>
        <text x="484" y="610" fill="white" font-size="10" font-weight="600" text-anchor="middle">smart_money_research</text>
        <text x="484" y="626" fill="#94a3b8" font-size="8" text-anchor="middle">patterns · leaderboard</text>

        <!-- db_maintenance.py -->
        <rect x="410" y="648" width="148" height="38" rx="6" fill="rgba(120, 53, 15, 0.3)" stroke="#fbbf24" stroke-width="1.5"/>
        <text x="484" y="672" fill="white" font-size="10" font-weight="600" text-anchor="middle">db_maintenance · daily</text>

        <!-- =================================================================
             CRON ORCHESTRATION (bottom)
             ================================================================= -->

        <!-- Cron boundary -->
        <rect x="20" y="790" width="260" height="100" rx="12" fill="rgba(251, 191, 36, 0.05)" stroke="#fbbf24" stroke-width="1" stroke-dasharray="8,4"/>
        <text x="30" y="808" fill="#fbbf24" font-size="10" font-weight="600">Cron Orchestration</text>
        <text x="30" y="824" fill="#94a3b8" font-size="8">*/10 scraper · */30 discovery</text>
        <text x="30" y="838" fill="#94a3b8" font-size="8">:10 enrich · :15 wallets · :20 cross</text>
        <text x="30" y="852" fill="#94a3b8" font-size="8">:25 social · :30 lifecycle</text>
        <text x="30" y="866" fill="#94a3b8" font-size="8">00:00 daily maintenance</text>
        <text x="30" y="880" fill="#fb7185" font-size="8">* * * * * trade_monitor (60s)</text>

        <!-- Test badge -->
        <rect x="300" y="860" width="100" height="22" rx="4" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1"/>
        <text x="350" y="875" fill="#34d399" font-size="8" font-weight="600" text-anchor="middle">100 tests ✓</text>

        <!-- Docker badge -->
        <rect x="300" y="832" width="90" height="22" rx="4" fill="rgba(8, 51, 68, 0.4)" stroke="#22d3ee" stroke-width="1"/>
        <text x="345" y="847" fill="#22d3ee" font-size="8" font-weight="600" text-anchor="middle">Docker ✓</text>

        <!-- =================================================================
             LEGEND (outside all boundaries)
             ================================================================= -->

        <text x="20" y="730" fill="white" font-size="10" font-weight="600">Legend</text>

        <rect x="20" y="740" width="16" height="10" rx="2" fill="rgba(6, 78, 59, 0.4)" stroke="#34d399" stroke-width="1"/>
        <text x="42" y="748" fill="#94a3b8" font-size="8">Scripts / Processing</text>

        <rect x="20" y="756" width="16" height="10" rx="2" fill="rgba(76, 29, 149, 0.4)" stroke="#a78bfa" stroke-width="1"/>
        <text x="42" y="764" fill="#94a3b8" font-size="8">Database (SQLite)</text>

        <rect x="20" y="772" width="16" height="10" rx="2" fill="rgba(120, 53, 15, 0.3)" stroke="#fbbf24" stroke-width="1"/>
        <text x="42" y="780" fill="#94a3b8" font-size="8">Cloud/API Service</text>

        <rect x="170" y="740" width="16" height="10" rx="2" fill="rgba(136, 19, 55, 0.4)" stroke="#fb7185" stroke-width="1"/>
        <text x="192" y="748" fill="#94a3b8" font-size="8">Security / AI</text>

        <rect x="170" y="756" width="16" height="10" rx="2" fill="rgba(8, 51, 68, 0.4)" stroke="#22d3ee" stroke-width="1"/>
        <text x="192" y="764" fill="#94a3b8" font-size="8">Frontend / Dashboard</text>

        <rect x="170" y="772" width="16" height="10" rx="2" fill="rgba(30, 41, 59, 0.5)" stroke="#94a3b8" stroke-width="1"/>
        <text x="192" y="780" fill="#94a3b8" font-size="8">External Data Source</text>

        <line x1="280" y1="745" x2="296" y2="745" stroke="#fb923c" stroke-width="1" stroke-dasharray="4,4"/>
        <text x="302" y="748" fill="#94a3b8" font-size="8">Feedback Loop</text>

        <line x1="280" y1="761" x2="296" y2="761" stroke="#fb7185" stroke-width="1" stroke-dasharray="4,4"/>
        <text x="302" y="764" fill="#94a3b8" font-size="8">AI/LLM Flow</text>

        <line x1="280" y1="777" x2="296" y2="777" stroke="#64748b" stroke-width="0.8" stroke-dasharray="3,6"/>
        <text x="302" y="780" fill="#94a3b8" font-size="8">Cron Trigger</text>

      </svg>

## Scripts

| Script | Purpose | Cron | Runtime |
|--------|---------|------|---------|
| `telegram_scraper.py` | Harvest contract addresses from 62 Telegram chats | `*/10 * * * *` | ~30s |
| `token_discovery.py` | Pull Dexscreener boosted + new profiles | `*/30 * * * *` | ~2s |
| `token_enricher.py` | 12-layer enrichment + scoring | `10 * * * *` | ~8 min |
| `wallet_tracker.py` | Discover + score wallets from top tokens | `15 * * * *` | ~15s |
| `smart_money_research.py` | Pattern learning + leaderboard | on-demand | ~5s |
| `db_maintenance.py` | Prune to top 1000 tokens + wallets | `0 0 * * *` | ~1s |

## Token Enrichment (12 Layers)

| Layer | Source | Data | Required |
|-------|--------|------|----------|
| 0 | Dexscreener | Volume, txns, FDV, liquidity, price | Yes |
| 1 | Surf | Social sentiment, mindshare, trending | No |
| 2 | GoPlus v2 | EVM security (honeypot, tax, mint) | No |
| 3 | RugCheck | Solana security (rug score, insiders) | No |
| 4 | Etherscan | Contract verification | No |
| 5 | De.Fi | Security analysis, holder concentration | No |
| 6 | Derived | Computed signals from Dexscreener data | No |
| 7 | CoinGecko | Market data, exchange listings | No |
| 8 | GMGN | Dev conviction, smart money, bot detection | No |
| 9 | Social | Telegram DB + composite social score | No |
| 10 | Zerion | Price, market cap, FDV, supply, verified | No |
| 11 | CoinStats | Risk score, liquidity score, volatility | No |

Each enricher is wrapped in try/except. If it fails, its fields are skipped but the pipeline continues. Only Layer 0 (Dexscreener) is required.

## Token Scoring (0-100)

Base score from 6 factors:

| Factor | Points | Description |
|--------|--------|-------------|
| Social momentum | 0-35 | Cross-channel calls + Telegram velocity |
| Freshness | 0-15 | Newer tokens score higher |
| Low FDV | 0-15 | Lower market cap = more upside |
| Volume | 0-24 | Absolute + accelerating volume |
| Transactions | 0-15 | Txn count + buy-heavy ratio |
| Price momentum | 0-10 | h1/h6/h24 price direction |

Multipliers: verified contract (+20%), dev holding (+25%), LP burned (+15%), smart wallets >20 (+15%), BINANCE listed (+10%), CoinGecko low risk (+5%)

**Steep decline penalties** (price collapse = unlikely to recover):

| Condition | Penalty |
|-----------|---------|
| h1 < -60% | score × 0.1 (rug in progress) |
| h1 < -40% | score × 0.2 |
| h1 < -25% | score × 0.5 |
| h6 < -70% | score × 0.1 (dead) |
| h6 < -50% | score × 0.2 (crashed) |
| h6 < -30% | score × 0.5 (declining) |
| Death spiral (vol dying + declining) | score × 0.3 |

## Wallet Scoring (0-100)

| Factor | Points | Description |
|--------|--------|-------------|
| Realized PNL | 0-35 | Profit TAKEN, not paper gains |
| Trade Count | 0-20 | Active wallets = established traders |
| Win Rate | 0-10 | Profitable tokens / total tokens |
| ROI | 0-10 | Average profit_change per token |
| Entry Timing | 0-8 | Earlier = better |
| Wallet Age | 0-5 | Longer = more established |
| Smart Tag | 0-5 | TOP1, KOL, SMART = better |
| Insider Bonus | 0-5 | MORE insider flags = BETTER |
| DeFi + Portfolio | 0-5 | Staked/borrowed positions |
| Social Presence | 0-2 | Linked Twitter = credibility |

**Penalties:**

| Condition | Penalty |
|-----------|---------|
| Round trips (profit without selling) | -15 each |
| Copy trade (always follows others) | -20 |
| Rug history (rugged anyone) | -100 each |

**Insider flags BOOST the score** — insiders know things, following them = alpha.

## Pattern Detection

| Pattern | Description |
|---------|-------------|
| SNIPER | Exits quickly, high sell ratio (>0.8) |
| SWING | Moderate holds, partial exits (0.4-0.8) |
| HOLDER | Few sells, long holds (<0.4) |
| DEGEN | >50 trades across >10 tokens |
| INSIDER | Flagged by heuristics (high ROI + few trades) |
| ACTIVE | >20 trades |

## Setup

### Prerequisites

```bash
# Node.js (for GMGN CLI + CoinStats MCP)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt install -y nodejs

# Surf CLI
curl -sSf https://agent.asksurf.ai/cli/releases/install.sh | bash

# Python dependencies
pip install telethon requests python-dotenv
```

### API Keys

Copy `.env.example` to `~/.hermes/.env` and fill in:

```bash
cp .env.example ~/.hermes/.env
```

Required keys:

| Key | Service | Free? |
|-----|---------|-------|
| `TG_API_ID` / `TG_API_HASH` | Telegram (my.telegram.org) | Yes |
| `GMGN_API_KEY` | GMGN (gmgn.ai/ai) | Yes |
| `ZERION_API_KEY` | Zerion (developers.zerion.io) | Yes |
| `COINSTATS_API_KEY` | CoinStats (coinstats.info/api) | Yes |
| `ETHERSCAN_API_KEY` | Etherscan (etherscan.io/apis) | Yes |
| `DEFI_API_KEY` | De.Fi (de.fi) | Yes |

Optional:

| Key | Service |
|-----|---------|
| `HELIUS_API_KEY` | Helius (Solana webhooks) |
| `ALCHEMY_API_KEY` | Alchemy (EVM webhooks) |
| `TELEGRAM_BOT_TOKEN` | Notifications |

### Run

```bash
# Test individual scripts
python3 telegram_scraper.py --dry-run
python3 token_discovery.py
python3 token_enricher.py --max-tokens 20
python3 wallet_tracker.py --min-score 5
python3 smart_money_research.py --leaderboard

# Or set up cron (recommended)
```

### Cron Setup

```bash
crontab -e
```

Add:

```cron
# Telegram contract harvesting (every 10 min)
*/10 * * * * /home/$USER/.hermes/scripts/telegram_scraper.py >> /home/$USER/.hermes/logs/tg_contract_scraper.log 2>&1

# Dexscreener token discovery (every 30 min)
*/30 * * * * /home/$USER/.hermes/scripts/token_discovery.py >> /home/$USER/.hermes/logs/token_discovery.log 2>&1

# Token enrichment (hourly at :10)
10 * * * * /home/$USER/.hermes/scripts/token_enricher.py >> /home/$USER/.hermes/logs/token_screener.log 2>&1

# Wallet tracking (hourly at :15)
15 * * * * /home/$USER/.hermes/scripts/wallet_tracker.py >> /home/$USER/.hermes/logs/wallet_tracker.log 2>&1

# Database maintenance (daily at midnight)
0 0 * * * /home/$USER/.hermes/scripts/db_maintenance.py >> /home/$USER/.hermes/logs/db_maintenance.log 2>&1
```

### Database Maintenance

The `db_maintenance.py` script runs daily to keep databases lean:

- **Contracts**: Keeps top 1000 by `(channel_count × mentions)`. Tokens younger than 7 days are never pruned.
- **Wallets**: Keeps top 1000 by `wallet_score`. Orphaned entries (tokens no longer in DB) are cleaned.

```bash
# Check current size
python3 db_maintenance.py --dry-run

# Override limits
python3 db_maintenance.py --max-tokens 2000 --max-wallets 500
```

## Data Flow

```
Every 10 min:  Telegram chats → central_contracts.db (dedup + increment)
Every 30 min:  Dexscreener   → central_contracts.db (boosted + profiles)
Hourly :10:    central_contracts.db → 12-layer enrichment → top100.json
Hourly :15:    top100.json → wallet discovery → wallet_tracker.db
Daily 00:00:   Prune both DBs to top 1000
```

## Rate Limits

| API | Delay | Notes |
|-----|-------|-------|
| Dexscreener | 1.0s | 300 tokens = 5 min |
| RugCheck | 0.5s | Free, Solana only |
| GoPlus v2 | 1.0s | EVM chains only |
| CoinGecko | 1.5s | Free tier |
| GMGN CLI | 0.5s | 2 calls per token |
| Zerion | 1.5s | Basic auth |
| De.Fi | 3.0s | GraphQL, 20 req/min |
| Etherscan | 0.25s | V2 API |

## License

MIT
