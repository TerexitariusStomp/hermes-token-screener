"""DeFi trading execution layer - multi-chain DEX aggregator + direct contract execution."""

from hermes_screener.trading.contract_executor import ContractExecutor
from hermes_screener.trading.dex_aggregator_trader import DexAggregatorTrader
from hermes_screener.trading.liquidity_daemon import LiquidityDaemon
from hermes_screener.trading.liquidity_manager import LiquidityManager
from hermes_screener.trading.portfolio_registry import PortfolioRegistry
from hermes_screener.trading.price_oracle import PriceOracle
from hermes_screener.trading.protocol_liquidity_executor import ProtocolLiquidityExecutor
from hermes_screener.trading.polymarket_complete_set_bot import run as run_polymarket_complete_set

__all__ = [
    "ContractExecutor",
    "DexAggregatorTrader",
    "LiquidityManager",
    "LiquidityDaemon",
    "PortfolioRegistry",
    "PriceOracle",
    "ProtocolLiquidityExecutor",
    "run_polymarket_complete_set",
]
