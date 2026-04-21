#!/usr/bin/env python3
"""
Thin wrapper - delegates to hermes_screener.trading.dex_aggregator_trader.
The canonical implementation lives in the package.
"""

from hermes_screener import tor_config  # noqa: F401
from hermes_screener.trading.dex_aggregator_trader import DexAggregatorTrader, main


if __name__ == "__main__":
    main()
