from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import requests

from hermes_screener.trading.portfolio_registry import TokenSpec


@dataclass(frozen=True)
class PricePoint:
    symbol: str
    chain: str
    address: str
    price_usd: float


class PriceOracle:
    """Coingecko-backed price oracle by token address with simple fallback values."""

    def __init__(self, cache_path: str | Path):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text())
        except Exception:
            return {}

    def _save_cache(self, data: dict) -> None:
        self.cache_path.write_text(json.dumps(data, indent=2))

    def get_prices(self, tokens: list[TokenSpec]) -> dict[str, float]:
        # Key by SYMBOL because planner currently consumes symbol keys.
        out: dict[str, float] = {}
        if not tokens:
            return out

        cache = self._load_cache()

        base_contracts = [t.address for t in tokens if t.chain == "base" and t.address.startswith("0x")]
        sol_contracts = [t.address for t in tokens if t.chain == "solana" and len(t.address) > 20]

        base_prices = {}
        sol_prices = {}
        if base_contracts:
            try:
                url = "https://api.coingecko.com/api/v3/simple/token_price/base"
                resp = requests.get(
                    url, params={"contract_addresses": ",".join(base_contracts), "vs_currencies": "usd"}, timeout=15
                )
                if resp.status_code == 200:
                    base_prices = resp.json()
            except Exception:
                base_prices = {}

        if sol_contracts:
            try:
                url = "https://api.coingecko.com/api/v3/simple/token_price/solana"
                resp = requests.get(
                    url, params={"contract_addresses": ",".join(sol_contracts), "vs_currencies": "usd"}, timeout=15
                )
                if resp.status_code == 200:
                    sol_prices = resp.json()
            except Exception:
                sol_prices = {}

        for t in tokens:
            key = f"{t.chain}:{t.address.lower()}"
            price = None
            if t.chain == "base":
                price = (base_prices.get(t.address.lower()) or {}).get("usd")
            elif t.chain == "solana":
                price = (sol_prices.get(t.address.lower()) or {}).get("usd")

            if price is None:
                # fallback cache
                price = cache.get(key)

            # stablecoin fallback
            if price is None and t.symbol in {"USDC", "USDT", "DAI"}:
                price = 1.0

            if price is not None:
                out[t.symbol] = float(price)
                cache[key] = float(price)

        self._save_cache(cache)
        return out
