#!/usr/bin/env python3
"""
Hermes Token Screener - Unified CLI Entry Point
Single command dispatcher for all screener operations.

Usage:
    hermes-cli.py discover [--chain CHAIN] [--limit N]
    hermes-cli.py score [--token TOKEN] [--chain CHAIN]
    hermes-cli.py enrich [--token TOKEN] [--wallet WALLET]
    hermes-cli.py trade [--daemon] [--interval SECONDS]
    hermes-cli.py monitor [--mode MODE]
    hermes-cli.py wallet [--enrich] [--top N]
    hermes-cli.py export [--format FORMAT] [--output PATH]
    hermes-cli.py daemon [--component screener|trading|all]
"""

import argparse
import logging
import signal
import sys

from hermes_screener import tor_config  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hermes-cli")


def cmd_discover(args: argparse.Namespace) -> None:
    """Discover new tokens across chains."""
    logger.info(f"Discovering tokens on {args.chain} (limit={args.limit})")
    try:
        from hermes_screener.async_enrichment import discover_tokens

        tokens = discover_tokens(chain=args.chain, limit=args.limit)
        logger.info(f"Found {len(tokens)} tokens")
        for t in tokens[: args.limit]:
            print(f"  {t.get('symbol', '?')}: {t.get('address', '?')}")
    except (ImportError, AttributeError):
        logger.error("Discovery module not available - install with: pip install hermes-token-screener[all]")


def cmd_score(args: argparse.Namespace) -> None:
    """Score tokens with revised methodology."""
    logger.info(f"Scoring token={args.token} on {args.chain}")
    try:
        from hermes_screener.revised_scoring import score_token

        result = score_token(args.token, chain=args.chain)
        print(f"Score: {result}")
    except (ImportError, AttributeError):
        logger.error("Scoring module not available")


def cmd_enrich(args: argparse.Namespace) -> None:
    """Enrich token or wallet data."""
    if args.wallet:
        logger.info(f"Enriching wallet: {args.wallet}")
        try:
            from hermes_screener.async_wallets import enrich_wallet

            result = enrich_wallet(args.wallet)
            print(f"Wallet enrichment: {result}")
        except (ImportError, AttributeError):
            logger.error("Wallet enrichment module not available")
    elif args.token:
        logger.info(f"Enriching token: {args.token}")
        try:
            from hermes_screener.async_enrichment import enrich_token

            result = enrich_token(args.token, chain=args.chain)
            print(f"Token enrichment: {result}")
        except (ImportError, AttributeError):
            logger.error("Token enrichment module not available")
    else:
        logger.error("Specify --token or --wallet")


def cmd_trade(args: argparse.Namespace) -> None:
    """Execute or daemonize trading."""
    import time

    from hermes_screener.trading.dex_aggregator_trader import DexAggregatorTrader

    trader = DexAggregatorTrader()

    if args.daemon:
        logger.info(f"Starting trading daemon (interval={args.interval}s)")

        def _sighandler(sig, frame):
            logger.info("Shutting down trading daemon...")
            sys.exit(0)

        signal.signal(signal.SIGTERM, _sighandler)
        signal.signal(signal.SIGINT, _sighandler)

        while True:
            try:
                trader.run()
                time.sleep(args.interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Trading cycle error: {e}")
                time.sleep(60)
    else:
        logger.info("Executing single trade cycle")
        trader.run()


def cmd_monitor(args: argparse.Namespace) -> None:
    """Monitor trading positions and signals."""
    logger.info(f"Monitoring mode: {args.mode}")
    try:
        from hermes_screener.trading.dex_aggregator_trader import DexAggregatorTrader

        trader = DexAggregatorTrader()
        bal = trader.get_balance("base")
        sol = trader.get_balance("solana")
        print(f"Base: {bal:.6f} ETH")
        print(f"Solana: {sol:.6f} SOL")
        holdings = trader.get_all_holdings()
        if holdings:
            for k, v in holdings.items():
                print(f"  {k}: {v['balance']:.4f}")
        else:
            print("No token holdings")
    except Exception as e:
        logger.error(f"Monitor error: {e}")


def cmd_wallet(args: argparse.Namespace) -> None:
    """Wallet operations - enrichment and tracking."""
    if args.enrich:
        logger.info(f"Enriching top {args.top} wallets")
        try:
            from hermes_screener.async_wallets import enrich_top_wallets

            enrich_top_wallets(limit=args.top)
        except (ImportError, AttributeError):
            logger.error("Wallet enrichment not available")
    else:
        logger.info("Wallet tracking active")
        try:
            from hermes_screener.async_wallets import list_wallets

            wallets = list_wallets()
            for w in wallets[: args.top]:
                print(f"  {w}")
        except (ImportError, AttributeError):
            logger.error("Wallet module not available")


def cmd_export(args: argparse.Namespace) -> None:
    """Export data to dashboard format."""
    logger.info(f"Exporting to {args.format} at {args.output}")
    try:
        from scripts.export_github_pages import main as export_main

        export_main()
    except ImportError:
        logger.error("Export module not available")


def cmd_daemon(args: argparse.Namespace) -> None:
    """Run long-running daemon components."""
    import time

    logger.info(f"Starting daemon component: {args.component}")

    def _sighandler(sig, frame):
        logger.info("Shutting down daemon...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sighandler)
    signal.signal(signal.SIGINT, _sighandler)

    if args.component in ("screener", "all"):
        logger.info("Screener daemon not yet integrated into CLI")

    if args.component in ("trading", "all"):
        from hermes_screener.trading.dex_aggregator_trader import DexAggregatorTrader

        trader = DexAggregatorTrader()
        while True:
            try:
                trader.run()
                time.sleep(300)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Trading daemon error: {e}")
                time.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hermes-cli",
        description="Hermes Token Screener - Unified CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # discover
    p_discover = subparsers.add_parser("discover", help="Discover new tokens")
    p_discover.add_argument("--chain", default="base", help="Chain to scan")
    p_discover.add_argument("--limit", type=int, default=20, help="Max tokens to return")

    # score
    p_score = subparsers.add_parser("score", help="Score tokens")
    p_score.add_argument("--token", required=True, help="Token address")
    p_score.add_argument("--chain", default="base", help="Chain")

    # enrich
    p_enrich = subparsers.add_parser("enrich", help="Enrich token/wallet data")
    p_enrich.add_argument("--token", help="Token address to enrich")
    p_enrich.add_argument("--wallet", help="Wallet address to enrich")
    p_enrich.add_argument("--chain", default="base", help="Chain")

    # trade
    p_trade = subparsers.add_parser("trade", help="Trading operations")
    p_trade.add_argument("--daemon", action="store_true", help="Run as daemon")
    p_trade.add_argument("--interval", type=int, default=300, help="Daemon interval (seconds)")

    # monitor
    p_monitor = subparsers.add_parser("monitor", help="Monitor positions and signals")
    p_monitor.add_argument("--mode", default="all", help="Monitor mode (all|positions|signals)")

    # wallet
    p_wallet = subparsers.add_parser("wallet", help="Wallet operations")
    p_wallet.add_argument("--enrich", action="store_true", help="Run enrichment")
    p_wallet.add_argument("--top", type=int, default=20, help="Top N wallets")

    # export
    p_export = subparsers.add_parser("export", help="Export dashboard data")
    p_export.add_argument("--format", default="github-pages", help="Export format")
    p_export.add_argument("--output", default=".", help="Output path")

    # daemon
    p_daemon = subparsers.add_parser("daemon", help="Run daemon components")
    p_daemon.add_argument(
        "--component",
        default="all",
        choices=["screener", "trading", "all"],
        help="Daemon component",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    COMMANDS = {
        "discover": cmd_discover,
        "score": cmd_score,
        "enrich": cmd_enrich,
        "trade": cmd_trade,
        "monitor": cmd_monitor,
        "wallet": cmd_wallet,
        "export": cmd_export,
        "daemon": cmd_daemon,
    }

    cmd_func = COMMANDS.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
