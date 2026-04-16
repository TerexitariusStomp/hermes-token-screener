"""
Async enrichment orchestrator — parallelizes all optional enrichment layers.

Instead of running layers 1-11 sequentially (~8 min), this runs them concurrently
using asyncio + httpx (~1-2 min depending on API latency).

Architecture:
  Layer 0 (Dexscreener): REQUIRED — runs first, blocking (enriches raw candidates with market data)
  Layers 1-11: OPTIONAL — all run in parallel via asyncio.gather()
    - HTTP enrichers (Surf, GoPlus, RugCheck, Etherscan, De.Fi, CoinGecko, Zerion):
      use httpx.AsyncClient with per-enricher semaphores for rate limiting
    - CLI enrichers (Surf CLI, GMGN MCP): use asyncio.to_thread()
    - Derived (no API): runs directly (pure computation)

Usage:
    from hermes_screener.async_enrichment import run_async_enrichment
    result = run_async_enrichment(candidates, max_enrich=300)

Or from token_enricher.py:
    python3 token_enricher.py --async    # uses async parallel enrichment
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from hermes_screener.config import settings
from hermes_screener.logging import get_logger, log_duration
from hermes_screener.metrics import metrics

log = get_logger("async_enrichment")


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP CLIENT FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def _make_client(
    base_url: str = "",
    headers: Optional[dict] = None,
    timeout: float = 15.0,
    max_connections: int = 10,
) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with sensible defaults."""
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=5,
    )
    return httpx.AsyncClient(
        base_url=base_url,
        headers=headers or {},
        timeout=httpx.Timeout(timeout, connect=5.0),
        limits=limits,
        follow_redirects=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ASYNC ENRICHER WRAPPERS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LayerResult:
    """Result from a single enrichment layer."""
    name: str
    success: bool
    enriched_count: int
    total_count: int
    elapsed: float
    error: Optional[str] = None


class AsyncDexscreenerEnricher:
    """Async Dexscreener — REQUIRED layer, enriches raw candidates."""

    BASE_URL = "https://api.dexscreener.com/latest/dex"

    def __init__(self, concurrency: int = 5):
        self.semaphore = asyncio.Semaphore(concurrency)

    async def enrich_batch(
        self,
        tokens: List[dict],
        client: httpx.AsyncClient,
    ) -> Tuple[List[dict], int]:
        """Enrich a batch of tokens with Dexscreener data."""
        tasks = [
            self._enrich_one(client, token, i, len(tokens))
            for i, token in enumerate(tokens)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched = []
        count = 0
        for r in results:
            if isinstance(r, dict) and r.get("dex"):
                enriched.append(r)
                count += 1
        return enriched, count

    async def _enrich_one(
        self,
        client: httpx.AsyncClient,
        token: dict,
        idx: int,
        total: int,
    ) -> dict:
        addr = token["contract_address"]
        async with self.semaphore:
            try:
                resp = await client.get(f"{self.BASE_URL}/tokens/{addr}")
                metrics.api_calls.labels(provider="dexscreener", status="ok").inc()
                if resp.status_code != 200:
                    return token
                data = resp.json()
                pairs = data.get("pairs", [])
                if not pairs:
                    return token

                best = max(
                    pairs, key=lambda p: (p.get("liquidity", {}).get("usd", 0) or 0)
                )
                txns = best.get("txns", {})
                volume = best.get("volume", {})
                price_change = best.get("priceChange", {})

                dex_data = {
                    "fdv": best.get("fdv"),
                    "market_cap": best.get("marketCap"),
                    "liquidity_usd": best.get("liquidity", {}).get("usd"),
                    "volume_m5": volume.get("m5", 0) or 0,
                    "volume_h1": volume.get("h1", 0) or 0,
                    "volume_h6": volume.get("h6", 0) or 0,
                    "volume_h24": volume.get("h24", 0) or 0,
                    "txns_m5": txns.get("m5", {}),
                    "txns_h1": txns.get("h1", {}),
                    "txns_h6": txns.get("h6", {}),
                    "txns_h24": txns.get("h24", {}),
                    "price_change_m5": price_change.get("m5"),
                    "price_change_h1": price_change.get("h1"),
                    "price_change_h6": price_change.get("h6"),
                    "price_change_h24": price_change.get("h24"),
                    "age_hours": self._age_hours(best.get("pairCreatedAt")),
                    "dex": best.get("dexId"),
                    "symbol": best.get("baseToken", {}).get("symbol"),
                    "name": best.get("baseToken", {}).get("name"),
                    "pair_address": best.get("pairAddress"),
                }
                # Correct chain from Dexscreener (fixes mislabeled BSC/Base tokens)
                ds_chain = best.get("chainId", "")
                if ds_chain and ds_chain != token.get("chain", ""):
                    token["chain"] = ds_chain
                return {**token, "dex": dex_data}
            except Exception as e:
                metrics.api_calls.labels(provider="dexscreener", status="error").inc()
                if (idx + 1) % 50 == 0:
                    log.warning("dexscreener_error", idx=idx + 1, total=total, error=str(e))
                return token

    @staticmethod
    def _age_hours(created_at_ms) -> Optional[float]:
        if not created_at_ms:
            return None
        return round((time.time() * 1000 - created_at_ms) / 3600000, 2)


class AsyncHttpEnricher:
    """Generic async HTTP enricher for per-token API calls."""

    def __init__(
        self,
        name: str,
        base_url: str = "",
        headers: Optional[dict] = None,
        concurrency: int = 3,
        delay: float = 0.5,
        timeout: float = 15.0,
    ):
        self.name = name
        self.base_url = base_url
        self.headers = headers or {}
        self.semaphore = asyncio.Semaphore(concurrency)
        self.delay = delay
        self.timeout = timeout
        self._last_request = 0.0

    async def enrich_batch(
        self,
        enrich_fn: Callable,
        tokens: List[dict],
        client: httpx.AsyncClient,
    ) -> Tuple[int, int]:
        """
        Run enrich_fn(token, client) on each token with rate limiting.
        enrich_fn should mutate the token dict in-place and return it.
        """
        tasks = []
        for i, token in enumerate(tokens):
            tasks.append(self._run_one(enrich_fn, token, client, i, len(tokens)))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if r is True)
        return success, len(tokens)

    async def _run_one(
        self,
        fn: Callable,
        token: dict,
        client: httpx.AsyncClient,
        idx: int,
        total: int,
    ) -> bool:
        async with self.semaphore:
            # Rate limiting
            elapsed = time.time() - self._last_request
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
            self._last_request = time.time()

            try:
                await fn(token, client)
                metrics.enrich_layer_calls.labels(layer=self.name, status="ok").inc()
                return True
            except Exception as e:
                metrics.enrich_layer_calls.labels(layer=self.name, status="error").inc()
                if (idx + 1) % 20 == 0:
                    log.warning(
                        "layer_error", layer=self.name, idx=idx + 1, total=total, error=str(e)
                    )
                return False


# ═══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL LAYER ASYNC IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

async def _enrich_goplus(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 2: GoPlus security check (EVM chains only)."""
    chain = token.get("chain", "").lower()
    if chain not in ("ethereum", "eth", "base", "binance", "bsc", "polygon"):
        return

    chain_map = {"eth": "1", "ethereum": "1", "bsc": "56", "binance": "56", "base": "8453"}
    chain_id = chain_map.get(chain, "")
    if not chain_id:
        return

    addr = token["contract_address"]
    resp = await client.get(
        f"https://api.gopluslabs.io/api/v2/token_security/{chain_id}",
        params={"contract_addresses": addr},
    )
    if resp.status_code != 200:
        return

    data = resp.json()
    result = data.get("result", {}).get(addr.lower(), {})
    if not result:
        return

    token["goplus"] = {
        "is_honeypot": result.get("is_honeypot") == "1",
        "buy_tax": float(result.get("buy_tax", 0) or 0),
        "sell_tax": float(result.get("sell_tax", 0) or 0),
        "can_take_back_ownership": result.get("can_take_back_ownership") == "1",
        "is_mintable": result.get("is_mintable") == "1",
        "owner_can_change_balance": result.get("owner_can_change_balance") == "1",
        "holder_count": int(result.get("holder_count", 0) or 0),
    }


async def _enrich_rugcheck(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 3: RugCheck (Solana only)."""
    if token.get("chain", "").lower() not in ("solana", "sol"):
        return

    addr = token["contract_address"]
    resp = await client.get(f"https://api.rugcheck.xyz/v1/tokens/{addr}/report")
    if resp.status_code != 200:
        return

    data = resp.json()
    token["rugcheck"] = {
        "score": data.get("score"),
        "risk_level": data.get("riskLevel"),
        "risks": data.get("risks", []),
        "insider_percentage": data.get("insiderAccounts", {}).get("percentage", 0),
        "top_holders_pct": sum(
            h.get("pct", 0) for h in data.get("topHolders", [])[:10]
        ),
        "lp_locked": data.get("markets", [{}])[0].get("lp", {}).get("lpLocked", False)
        if data.get("markets")
        else False,
    }


async def _enrich_etherscan(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 4: Etherscan contract verification."""
    chain = token.get("chain", "").lower()
    if chain not in ("ethereum", "eth", "base"):
        return

    addr = token["contract_address"]
    api_key = settings.etherscan_api_key or "3VY4WXTCKJWC3PQHDTK38MVR73AMPV5A4S"
    resp = await client.get(
        "https://api.etherscan.io/v2/api",
        params={
            "chainid": 8453 if chain == "base" else 1,
            "module": "contract",
            "action": "getsourcecode",
            "address": addr,
            "apikey": api_key,
        },
    )
    if resp.status_code != 200:
        return

    data = resp.json()
    results = data.get("result", [{}])
    if not results:
        return

    r = results[0]
    token["etherscan"] = {
        "is_verified": r.get("ABI") != "Contract source code not verified",
        "compiler": r.get("CompilerVersion", ""),
        "optimization": r.get("OptimizationUsed", "") == "1",
        "contract_name": r.get("ContractName", ""),
    }


async def _enrich_defi(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 5: De.Fi security analysis."""
    chain = token.get("chain", "").lower()
    chain_ids = {
        "ethereum": 1, "eth": 1, "binance": 2, "bsc": 2,
        "solana": 12, "base": 49,
    }
    de_fi_chain = chain_ids.get(chain)
    if de_fi_chain is None:
        return

    addr = token["contract_address"]
    headers = {"Content-Type": "application/json"}
    if settings.defi_api_key:
        headers["X-Api-Key"] = settings.defi_api_key

    resp = await client.post(
        "https://public-api.de.fi/graphql",
        json={
            "query": """
                query GetScannerReport($chain: Int!, $address: String!) {
                    authenticatedGetAccessToSmartContractSecurityDatabase(chain: $chain, address: $address) {
                        issues { name severity }
                        scScore { score }
                        isHoneypot
                    }
                }
            """,
            "variables": {"chain": de_fi_chain, "address": addr},
        },
        headers=headers,
    )
    if resp.status_code != 200:
        return

    data = resp.json()
    report = data.get("data", {}).get("authenticatedGetAccessToSmartContractSecurityDatabase", {})
    if not report:
        return

    issues = report.get("issues", [])
    score_obj = report.get("scScore", {})
    token["defi"] = {
        "score": score_obj.get("score"),
        "issue_count": len(issues),
        "critical_issues": len([i for i in issues if i.get("severity") == "CRITICAL"]),
        "is_honeypot": report.get("isHoneypot", False),
    }


async def _enrich_coingecko(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 7: CoinGecko market data."""
    addr = token["contract_address"]
    params = {"localization": "false", "tickers": "false", "community_data": "false"}
    if settings.coingecko_api_key:
        params["x_cg_demo_api_key"] = settings.coingecko_api_key

    resp = await client.get(
        f"https://api.coingecko.com/api/v3/coins/{addr}/contract/{addr}",
        params=params,
    )
    if resp.status_code != 200:
        # Try Solana contract lookup
        resp = await client.get(
            f"https://api.coingecko.com/api/v3/coins/solana/contract/{addr}",
            params=params,
        )
        if resp.status_code != 200:
            return

    data = resp.json()
    token["coingecko"] = {
        "sentiment_up": data.get("sentiment_votes_up_percentage", 0),
        "sentiment_down": data.get("sentiment_votes_down_percentage", 0),
        "ath": data.get("market_data", {}).get("ath", {}).get("usd"),
        "ath_change_pct": data.get("market_data", {}).get("ath_change_percentage", {}).get("usd"),
        "exchanges": len(data.get("tickers", [])) if data.get("tickers") else 0,
        "categories": data.get("categories", []),
    }


async def _enrich_zerion(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 10: Zerion portfolio data."""
    if not settings.zerion_api_key:
        return

    addr = token["contract_address"]
    resp = await client.get(
        f"https://api.zerion.io/v1/wallets/{addr}/portfolio",
        headers={"Authorization": f"Basic {settings.zerion_api_key}"},
    )
    if resp.status_code != 200:
        return

    data = resp.json()
    portfolio = data.get("data", {}).get("attributes", {})
    token["zerion"] = {
        "total_value": portfolio.get("total", {}).get("positions", 0),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENRICHER WRAPPERS (async via to_thread)
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_cli_enricher(name: str, sync_fn: Callable, enriched: list) -> LayerResult:
    """Run a synchronous CLI enricher in a thread."""
    start = time.time()
    try:
        _, count = await asyncio.to_thread(sync_fn, enriched)
        elapsed = time.time() - start
        metrics.enrich_layer_calls.labels(layer=name, status="ok").inc()
        return LayerResult(name=name, success=True, enriched_count=count, total_count=len(enriched), elapsed=elapsed)
    except Exception as e:
        elapsed = time.time() - start
        metrics.enrich_layer_calls.labels(layer=name, status="error").inc()
        log.warning("cli_layer_failed", layer=name, error=str(e))
        return LayerResult(name=name, success=False, enriched_count=0, total_count=len(enriched), elapsed=elapsed, error=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# DERIVED (no API, pure computation)
# ═══════════════════════════════════════════════════════════════════════════════

async def _enrich_derived(enriched: list) -> int:
    """Layer 6: Computed security signals (no API needed)."""
    count = 0
    for token in enriched:
        derived = {}

        # FDV vs liquidity ratio
        fdv = token.get("dex", {}).get("fdv") or token.get("fdv")
        liq = token.get("dex", {}).get("liquidity_usd") or token.get("liquidity_usd")
        if fdv and liq and fdv > 0:
            ratio = liq / fdv
            derived["liq_fdv_ratio"] = round(ratio, 4)
            derived["liq_risk"] = (
                "critical" if ratio < 0.02
                else "high" if ratio < 0.05
                else "moderate" if ratio < 0.10
                else "healthy"
            )

        # Tax risk (from GoPlus)
        goplus = token.get("goplus", {})
        if goplus:
            buy_tax = goplus.get("buy_tax", 0)
            sell_tax = goplus.get("sell_tax", 0)
            if buy_tax > 0.10 or sell_tax > 0.10:
                derived["tax_risk"] = "high"
            elif buy_tax > 0.05 or sell_tax > 0.05:
                derived["tax_risk"] = "moderate"
            else:
                derived["tax_risk"] = "low"

        if derived:
            token["derived"] = derived
            count += 1

    return count


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

async def run_async_enrichment(
    candidates: List[dict],
    max_enrich: int = 300,
) -> Tuple[List[dict], List[LayerResult]]:
    """
    Run all enrichment layers asynchronously.

    Phase 1: Dexscreener (REQUIRED, blocks until complete)
    Phase 2: All optional layers in parallel via asyncio.gather()

    Returns (enriched_tokens, layer_results).
    """
    from hermes_screener.async_enrichment import (
        AsyncDexscreenerEnricher,
        AsyncHttpEnricher,
        _enrich_goplus,
        _enrich_rugcheck,
        _enrich_etherscan,
        _enrich_defi,
        _enrich_coingecko,
        _enrich_zerion,
        _enrich_derived,
        _run_cli_enricher,
        LayerResult,
        _make_client,
    )

    # Import sync enrichers for CLI-based layers
    import sys
    sys.path.insert(0, str(settings.hermes_home / "scripts"))
    # These will be imported lazily to avoid circular imports

    results: List[LayerResult] = []
    total_candidates = len(candidates)

    async with _make_client() as client:
        # ═══ Phase 1: Dexscreener (REQUIRED) ═══
        log.info("phase1_dexscreener", tokens=len(candidates))
        start = time.time()
        dex = AsyncDexscreenerEnricher(concurrency=5)
        enriched, dex_count = await dex.enrich_batch(candidates[:max_enrich], client)
        elapsed = time.time() - start

        if not enriched:
            log.error("dexscreener_empty", candidates=len(candidates))
            return [], [LayerResult("Dexscreener", False, 0, total_candidates, elapsed, "no results")]

        results.append(LayerResult("Dexscreener", True, dex_count, total_candidates, elapsed))
        log.info("phase1_complete", enriched=dex_count, total=total_candidates, elapsed=round(elapsed, 1))

        # ═══ Phase 2: All optional layers in parallel ═══
        log.info("phase2_parallel", layers=11, tokens=len(enriched))

        # GoPlus
        goplus_enricher = AsyncHttpEnricher("GoPlus", concurrency=3, delay=0.3)

        # RugCheck
        rugcheck_enricher = AsyncHttpEnricher("RugCheck", concurrency=3, delay=0.3)

        # Etherscan
        etherscan_enricher = AsyncHttpEnricher("Etherscan", concurrency=2, delay=0.25)

        # De.Fi
        defi_enricher = AsyncHttpEnricher("De.Fi", concurrency=2, delay=1.0)

        # CoinGecko
        coingecko_enricher = AsyncHttpEnricher("CoinGecko", concurrency=2, delay=1.5)

        # Zerion
        zerion_enricher = AsyncHttpEnricher("Zerion", concurrency=2, delay=1.0)

        # Define all parallel tasks
        async def run_goplus():
            start = time.time()
            try:
                ok, total = await goplus_enricher.enrich_batch(_enrich_goplus, enriched, client)
                return LayerResult("GoPlus", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult("GoPlus", False, 0, len(enriched), time.time() - start, str(e))

        async def run_rugcheck():
            start = time.time()
            try:
                ok, total = await rugcheck_enricher.enrich_batch(_enrich_rugcheck, enriched, client)
                return LayerResult("RugCheck", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult("RugCheck", False, 0, len(enriched), time.time() - start, str(e))

        async def run_etherscan():
            start = time.time()
            try:
                ok, total = await etherscan_enricher.enrich_batch(_enrich_etherscan, enriched, client)
                return LayerResult("Etherscan", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult("Etherscan", False, 0, len(enriched), time.time() - start, str(e))

        async def run_defi():
            start = time.time()
            try:
                ok, total = await defi_enricher.enrich_batch(_enrich_defi, enriched, client)
                return LayerResult("De.Fi", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult("De.Fi", False, 0, len(enriched), time.time() - start, str(e))

        async def run_coingecko():
            start = time.time()
            try:
                ok, total = await coingecko_enricher.enrich_batch(_enrich_coingecko, enriched, client)
                return LayerResult("CoinGecko", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult("CoinGecko", False, 0, len(enriched), time.time() - start, str(e))

        async def run_zerion():
            start = time.time()
            try:
                ok, total = await zerion_enricher.enrich_batch(_enrich_zerion, enriched, client)
                return LayerResult("Zerion", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult("Zerion", False, 0, len(enriched), time.time() - start, str(e))

        async def run_derived():
            start = time.time()
            try:
                count = await _enrich_derived(enriched)
                return LayerResult("Derived", True, count, len(enriched), time.time() - start)
            except Exception as e:
                return LayerResult("Derived", False, 0, len(enriched), time.time() - start, str(e))

        # Surf, GMGN — CLI-based, run in threads
        async def run_surf():
            try:
                from token_enricher import SurfEnricher
                return await _run_cli_enricher("Surf", lambda t: SurfEnricher().enrich_batch(t), enriched)
            except ImportError:
                return LayerResult("Surf", False, 0, len(enriched), 0, "import failed")

        async def run_gmgn():
            try:
                from token_enricher import GMGNEnricher
                return await _run_cli_enricher("GMGN", lambda t: GMGNEnricher().enrich_batch(t), enriched)
            except ImportError:
                return LayerResult("GMGN", False, 0, len(enriched), 0, "import failed")


        async def run_social():
            try:
                from token_enricher import SocialSignalEnricher
                return await _run_cli_enricher("Social", lambda t: SocialSignalEnricher().enrich_batch(t), enriched)
            except ImportError:
                return LayerResult("Social", False, 0, len(enriched), 0, "import failed")

        # ═══ RUN ALL IN PARALLEL ═══
        phase2_start = time.time()
        layer_results = await asyncio.gather(
            run_goplus(),
            run_rugcheck(),
            run_etherscan(),
            run_defi(),
            run_coingecko(),
            run_zerion(),
            run_derived(),
            run_surf(),
            run_gmgn(),
            run_social(),
            return_exceptions=True,
        )

        phase2_elapsed = time.time() - phase2_start
        for r in layer_results:
            if isinstance(r, LayerResult):
                results.append(r)
                status = "OK" if r.success else "SKIP"
                log.info(
                    "layer_result",
                    layer=r.name,
                    status=status,
                    enriched=r.enriched_count,
                    elapsed=round(r.elapsed, 1),
                )
            elif isinstance(r, Exception):
                log.error("layer_exception", error=str(r))
                results.append(LayerResult("Unknown", False, 0, 0, 0, str(r)))

        log.info(
            "phase2_complete",
            elapsed=round(phase2_elapsed, 1),
            layers_ok=sum(1 for r in results if r.success),
            layers_total=len(results),
        )

        # Record pipeline metrics
        total_elapsed = sum(r.elapsed for r in results)
        metrics.pipeline_runs.inc()
        metrics.pipeline_duration.observe(total_elapsed)
        metrics.tokens_enriched.set(len(enriched))
        metrics.last_run_timestamp.set(time.time())

        return enriched, results


def run_async_enrichment_sync(
    candidates: List[dict],
    max_enrich: int = 300,
) -> Tuple[List[dict], List[LayerResult]]:
    """Synchronous wrapper for run_async_enrichment()."""
    return asyncio.run(run_async_enrichment(candidates, max_enrich))
