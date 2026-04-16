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
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from hermes_screener.config import settings
from hermes_screener.logging import get_logger
from hermes_screener.metrics import metrics

log = get_logger("async_enrichment")


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP CLIENT FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


def _make_client(
    base_url: str = "",
    headers: dict | None = None,
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
    error: str | None = None


class AsyncDexscreenerEnricher:
    """Async Dexscreener — REQUIRED layer, enriches raw candidates."""

    BASE_URL = "https://api.dexscreener.com/latest/dex"

    def __init__(self, concurrency: int = 5):
        self.semaphore = asyncio.Semaphore(concurrency)

    async def enrich_batch(
        self,
        tokens: list[dict],
        client: httpx.AsyncClient,
    ) -> tuple[list[dict], int]:
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
                # Only correct chain from Dexscreener when original is unreliable.
                # GMGN/GMGN-trenches sources already know their chain.
                # Telegram scraper defaults 0x addresses to 'ethereum' which may be wrong.
                ds_chain = best.get("chainId", "")
                orig_chain = token.get("chain", "")
                reliable_sources = {"gmgn_trenches", "gmgn_trending"}
                is_reliable = any(
                    (token.get("last_source", "") or "").startswith(s)
                    for s in reliable_sources
                )
                if ds_chain and ds_chain != orig_chain and not is_reliable:
                    token["chain"] = ds_chain

                # Extract social links from Dexscreener info
                info = best.get("info", {})
                socials = info.get("socials", [])
                websites = info.get("websites", [])
                for s in socials:
                    stype = s.get("type", "")
                    surl = s.get("url", "")
                    if stype == "twitter":
                        dex_data["twitter_url"] = surl
                    elif stype == "telegram":
                        dex_data["telegram_url"] = surl
                if websites:
                    dex_data["website_url"] = websites[0].get("url", "")

                return {**token, "dex": dex_data}
            except Exception as e:
                metrics.api_calls.labels(provider="dexscreener", status="error").inc()
                if (idx + 1) % 50 == 0:
                    log.warning(
                        "dexscreener_error", idx=idx + 1, total=total, error=str(e)
                    )
                return token

    @staticmethod
    def _age_hours(created_at_ms) -> float | None:
        if not created_at_ms:
            return None
        return round((time.time() * 1000 - created_at_ms) / 3600000, 2)  # type: ignore[no-any-return]


class AsyncHttpEnricher:
    """Generic async HTTP enricher for per-token API calls."""

    def __init__(
        self,
        name: str,
        base_url: str = "",
        headers: dict | None = None,
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
        tokens: list[dict],
        client: httpx.AsyncClient,
    ) -> tuple[int, int]:
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
                        "layer_error",
                        layer=self.name,
                        idx=idx + 1,
                        total=total,
                        error=str(e),
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

    chain_map = {
        "eth": "1",
        "ethereum": "1",
        "bsc": "56",
        "binance": "56",
        "base": "8453",
    }
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
        "lp_locked": (
            data.get("markets", [{}])[0].get("lp", {}).get("lpLocked", False)
            if data.get("markets")
            else False
        ),
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
        "ethereum": 1,
        "eth": 1,
        "binance": 2,
        "bsc": 2,
        "solana": 12,
        "base": 49,
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
    report = data.get("data", {}).get(
        "authenticatedGetAccessToSmartContractSecurityDatabase", {}
    )
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
        "ath_change_pct": data.get("market_data", {})
        .get("ath_change_percentage", {})
        .get("usd"),
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


async def _enrich_solscan(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 14: Solscan token data (Solana only) - Free tier endpoints."""
    chain = token.get("chain", "").lower()
    if chain not in ("solana", "sol"):
        return

    addr = token["contract_address"]
    headers = {
        "Accept": "application/json",
    }

    try:
        # Use free tier endpoints (no authentication required)
        # Get token info
        resp = await client.get(
            f"https://public-api.solscan.io/token/meta?tokenAddress={addr}",
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return

        data = resp.json()

        # Get token holders (free tier)
        resp_holders = await client.get(
            f"https://public-api.solscan.io/token/holders?tokenAddress={addr}&limit=10",
            headers=headers,
            timeout=10.0,
        )
        holders_data = resp_holders.json() if resp_holders.status_code == 200 else {}

        # Get token transfers (free tier)
        resp_transfers = await client.get(
            f"https://public-api.solscan.io/token/transfer?tokenAddress={addr}&limit=10",
            headers=headers,
            timeout=10.0,
        )
        transfers_data = (
            resp_transfers.json() if resp_transfers.status_code == 200 else {}
        )

        token["solscan"] = {
            "name": data.get("name", ""),
            "symbol": data.get("symbol", ""),
            "decimals": data.get("decimals", 0),
            "supply": data.get("supply", 0),
            "market_cap": data.get("marketCap", 0),
            "price_usd": data.get("priceUsd", 0),
            "price_change_24h": data.get("priceChange24h", 0),
            "volume_24h": data.get("volume24h", 0),
            "holder_count": data.get("holder", 0),
            "top_holders": holders_data.get("data", []),
            "recent_transfers": transfers_data.get("data", []),
        }

    except Exception:
        # Silently fail - don't break the pipeline
        pass


async def _enrich_helius(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 15: Helius token data (Solana only)."""
    if not settings.helius_api_key:
        return

    chain = token.get("chain", "").lower()
    if chain not in ("solana", "sol"):
        return

    addr = token["contract_address"]

    try:
        # Get token metadata
        resp = await client.post(
            f"https://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAsset",
                "params": {"id": addr, "displayOptions": {"showFungibleTokens": True}},
            },
            timeout=10.0,
        )

        if resp.status_code != 200:
            return

        data = resp.json()
        result = data.get("result", {})

        # Get token holders (using getTokenAccounts)
        resp_holders = await client.post(
            f"https://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccounts",
                "params": {"mint": addr, "limit": 10},
            },
            timeout=10.0,
        )
        holders_data = resp_holders.json() if resp_holders.status_code == 200 else {}

        token["helius"] = {
            "name": result.get("content", {}).get("metadata", {}).get("name", ""),
            "symbol": result.get("content", {}).get("metadata", {}).get("symbol", ""),
            "decimals": result.get("token_info", {}).get("decimals", 0),
            "supply": result.get("token_info", {}).get("supply", 0),
            "price_per_token": result.get("token_info", {})
            .get("price_info", {})
            .get("price_per_token", 0),
            "total_price": result.get("token_info", {})
            .get("price_info", {})
            .get("total_price", 0),
            "currency": result.get("token_info", {})
            .get("price_info", {})
            .get("currency", ""),
            "holder_count": len(
                holders_data.get("result", {}).get("token_accounts", [])
            ),
        }

    except Exception:
        # Silently fail - don't break the pipeline
        pass


async def _enrich_birdeye(token: dict, client: httpx.AsyncClient) -> None:
    """Layer 16: Birdeye token data (Multi-chain)."""
    if not settings.birdeye_api_key:
        return

    addr = token["contract_address"]
    chain = token.get("chain", "").lower()

    # Map chain to Birdeye chain identifier
    chain_map = {
        "solana": "solana",
        "sol": "solana",
        "ethereum": "ethereum",
        "eth": "ethereum",
        "base": "base",
        "binance": "bsc",
        "bsc": "bsc",
        "polygon": "polygon",
    }

    birdeye_chain = chain_map.get(chain, "solana")

    headers = {"X-API-KEY": settings.birdeye_api_key, "accept": "application/json"}

    try:
        # Get token overview
        resp = await client.get(
            f"https://public-api.birdeye.so/defi/token_overview?address={addr}&chain={birdeye_chain}",
            headers=headers,
            timeout=10.0,
        )

        if resp.status_code != 200:
            return

        data = resp.json()
        token_data = data.get("data", {})

        # Get token holders (if available)
        resp_holders = await client.get(
            f"https://public-api.birdeye.so/defi/token_holder?address={addr}&chain={birdeye_chain}&limit=10",
            headers=headers,
            timeout=10.0,
        )
        holders_data = resp_holders.json() if resp_holders.status_code == 200 else {}

        # Get token trading data
        resp_trading = await client.get(
            f"https://public-api.birdeye.so/defi/token_trading_data?address={addr}&chain={birdeye_chain}&time_frame=24h",
            headers=headers,
            timeout=10.0,
        )
        trading_data = resp_trading.json() if resp_trading.status_code == 200 else {}

        token["birdeye"] = {
            "name": token_data.get("name", ""),
            "symbol": token_data.get("symbol", ""),
            "decimals": token_data.get("decimals", 0),
            "supply": token_data.get("supply", 0),
            "market_cap": token_data.get("mc", 0),
            "fdv": token_data.get("fdv", 0),
            "liquidity": token_data.get("liquidity", 0),
            "price": token_data.get("price", 0),
            "price_change_24h": token_data.get("priceChange24h", 0),
            "volume_24h": token_data.get("v24h", 0),
            "volume_24h_change": token_data.get("v24hChange", 0),
            "trade_24h": token_data.get("trade24h", 0),
            "trade_24h_change": token_data.get("trade24hChange", 0),
            "holder_count": token_data.get("holder", 0),
            "top_holders": holders_data.get("data", {}).get("items", []),
            "trading_data": trading_data.get("data", {}),
        }

    except Exception:
        # Silently fail - don't break the pipeline
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENRICHER WRAPPERS (async via to_thread)
# ═══════════════════════════════════════════════════════════════════════════════


async def _run_cli_enricher(
    name: str, sync_fn: Callable, enriched: list
) -> LayerResult:
    """Run a synchronous CLI enricher in a thread."""
    start = time.time()
    try:
        _, count = await asyncio.to_thread(sync_fn, enriched)
        elapsed = time.time() - start
        metrics.enrich_layer_calls.labels(layer=name, status="ok").inc()
        return LayerResult(
            name=name,
            success=True,
            enriched_count=count,
            total_count=len(enriched),
            elapsed=elapsed,
        )
    except Exception as e:
        elapsed = time.time() - start
        metrics.enrich_layer_calls.labels(layer=name, status="error").inc()
        log.warning("cli_layer_failed", layer=name, error=str(e))
        return LayerResult(
            name=name,
            success=False,
            enriched_count=0,
            total_count=len(enriched),
            elapsed=elapsed,
            error=str(e),
        )


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
                "critical"
                if ratio < 0.02
                else (
                    "high"
                    if ratio < 0.05
                    else "moderate" if ratio < 0.10 else "healthy"
                )
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
    candidates: list[dict],
    max_enrich: int = 300,
) -> tuple[list[dict], list[LayerResult]]:
    """
    Run all enrichment layers asynchronously.

    Phase 1: Dexscreener (REQUIRED, blocks until complete)
    Phase 2: All optional layers in parallel via asyncio.gather()

    Returns (enriched_tokens, layer_results).
    """
    # Import sync enrichers for CLI-based layers
    import sys

    from hermes_screener.async_enrichment import (
        AsyncDexscreenerEnricher,
        AsyncHttpEnricher,
        LayerResult,
        _enrich_birdeye,
        _enrich_coingecko,
        _enrich_defi,
        _enrich_derived,
        _enrich_etherscan,
        _enrich_goplus,
        _enrich_helius,
        _enrich_rugcheck,
        _enrich_solscan,
        _enrich_zerion,
        _make_client,
        _run_cli_enricher,
    )

    sys.path.insert(0, str(settings.hermes_home / "scripts"))
    # These will be imported lazily to avoid circular imports

    results: list[LayerResult] = []
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
            return [], [
                LayerResult(
                    "Dexscreener", False, 0, total_candidates, elapsed, "no results"
                )
            ]

        results.append(
            LayerResult("Dexscreener", True, dex_count, total_candidates, elapsed)
        )
        log.info(
            "phase1_complete",
            enriched=dex_count,
            total=total_candidates,
            elapsed=round(elapsed, 1),
        )

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

        # Solscan
        solscan_enricher = AsyncHttpEnricher("Solscan", concurrency=2, delay=0.5)

        # Helius
        helius_enricher = AsyncHttpEnricher("Helius", concurrency=2, delay=0.5)

        # Birdeye
        birdeye_enricher = AsyncHttpEnricher("Birdeye", concurrency=2, delay=0.5)

        # Define all parallel tasks
        async def run_goplus():
            start = time.time()
            try:
                ok, total = await goplus_enricher.enrich_batch(
                    _enrich_goplus, enriched, client
                )
                return LayerResult("GoPlus", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "GoPlus", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_rugcheck():
            start = time.time()
            try:
                ok, total = await rugcheck_enricher.enrich_batch(
                    _enrich_rugcheck, enriched, client
                )
                return LayerResult("RugCheck", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "RugCheck", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_etherscan():
            start = time.time()
            try:
                ok, total = await etherscan_enricher.enrich_batch(
                    _enrich_etherscan, enriched, client
                )
                return LayerResult("Etherscan", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "Etherscan", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_defi():
            start = time.time()
            try:
                ok, total = await defi_enricher.enrich_batch(
                    _enrich_defi, enriched, client
                )
                return LayerResult("De.Fi", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "De.Fi", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_coingecko():
            start = time.time()
            try:
                ok, total = await coingecko_enricher.enrich_batch(
                    _enrich_coingecko, enriched, client
                )
                return LayerResult("CoinGecko", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "CoinGecko", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_zerion():
            start = time.time()
            try:
                ok, total = await zerion_enricher.enrich_batch(
                    _enrich_zerion, enriched, client
                )
                return LayerResult("Zerion", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "Zerion", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_solscan():
            start = time.time()
            try:
                ok, total = await solscan_enricher.enrich_batch(
                    _enrich_solscan, enriched, client
                )
                return LayerResult("Solscan", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "Solscan", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_helius():
            start = time.time()
            try:
                ok, total = await helius_enricher.enrich_batch(
                    _enrich_helius, enriched, client
                )
                return LayerResult("Helius", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "Helius", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_birdeye():
            start = time.time()
            try:
                ok, total = await birdeye_enricher.enrich_batch(
                    _enrich_birdeye, enriched, client
                )
                return LayerResult("Birdeye", True, ok, total, time.time() - start)
            except Exception as e:
                return LayerResult(
                    "Birdeye", False, 0, len(enriched), time.time() - start, str(e)
                )

        async def run_derived():
            start = time.time()
            try:
                count = await _enrich_derived(enriched)
                return LayerResult(
                    "Derived", True, count, len(enriched), time.time() - start
                )
            except Exception as e:
                return LayerResult(
                    "Derived", False, 0, len(enriched), time.time() - start, str(e)
                )

        # Surf, GMGN — CLI-based, run in threads
        async def run_surf():
            try:
                from token_enricher import SurfEnricher

                return await _run_cli_enricher(
                    "Surf", lambda t: SurfEnricher().enrich_batch(t), enriched
                )
            except ImportError:
                return LayerResult("Surf", False, 0, len(enriched), 0, "import failed")

        async def run_gmgn():
            try:
                from token_enricher import GMGNEnricher

                return await _run_cli_enricher(
                    "GMGN", lambda t: GMGNEnricher().enrich_batch(t), enriched
                )
            except ImportError:
                return LayerResult("GMGN", False, 0, len(enriched), 0, "import failed")

        async def run_social():
            try:
                from scripts.token_enricher import SocialSignalEnricher

                return await _run_cli_enricher(
                    "Social", lambda t: SocialSignalEnricher().enrich_batch(t), enriched
                )
            except ImportError:
                return LayerResult(
                    "Social", False, 0, len(enriched), 0, "import failed"
                )

        # ═══ RUN ALL IN PARALLEL ═══
        phase2_start = time.time()
        layer_results = await asyncio.gather(
            run_goplus(),
            run_rugcheck(),
            run_etherscan(),
            run_defi(),
            run_coingecko(),
            run_zerion(),
            run_solscan(),
            run_helius(),
            run_birdeye(),
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
    candidates: list[dict],
    max_enrich: int = 300,
) -> tuple[list[dict], list[LayerResult]]:
    """Synchronous wrapper for run_async_enrichment()."""
    return asyncio.run(run_async_enrichment(candidates, max_enrich))
