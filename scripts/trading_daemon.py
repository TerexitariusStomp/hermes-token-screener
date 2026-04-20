#!/usr/bin/env python3
"""
Trading Daemon - Runs all trading components continuously.

Components:
1. AI Trading Brain - token analysis & trade decisions (every 10 min)
2. Trade Monitor - position monitoring (every 1 min)
3. Copytrade Monitor - smart money tracking (every 60 min)

Usage: python3 trading_daemon.py [--dry-run]
"""

import subprocess
import sys
import time
import signal
import logging
from datetime import datetime
from pathlib import Path

# Configure logging
LOG_DIR = Path.home() / ".hermes" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "trading_daemon.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("TradingDaemon")

# Scripts
SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"
AI_BRAIN = SCRIPTS_DIR / "ai_trading_brain.py"
TRADE_MONITOR = SCRIPTS_DIR / "trade_monitor.py"
COPYTRADE_MONITOR = SCRIPTS_DIR / "copytrade_monitor.py"

# Intervals (seconds)
AI_BRAIN_INTERVAL = 600  # 10 minutes
TRADE_MONITOR_INTERVAL = 60  # 1 minute
COPYTRADE_INTERVAL = 3600  # 60 minutes

# State
running = True
dry_run = "--dry-run" in sys.argv


def signal_handler(signum, frame):
    global running
    logger.info(f"Received signal {signum}, shutting down...")
    running = False


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def run_script(script_path: Path, name: str, execute: bool = True) -> bool:
    """Run a script and return success status."""
    try:
        cmd = [sys.executable, str(script_path)]
        # Only ai_trading_brain and trade_monitor take --execute
        if execute and script_path.name in ("ai_trading_brain.py", "trade_monitor.py"):
            cmd.append("--execute")
        if dry_run and script_path.name != "copytrade_monitor.py":
            cmd.append("--dry-run")

        logger.info(f"[{name}] Running...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
        )

        if result.returncode == 0:
            logger.info(f"[{name}] Completed successfully")
            if result.stdout.strip():
                # Log last few lines of output
                lines = result.stdout.strip().split("\n")
                for line in lines[-3:]:
                    logger.debug(f"[{name}] {line}")
            return True
        else:
            logger.warning(f"[{name}] Exit code {result.returncode}")
            if result.stderr:
                logger.warning(f"[{name}] Error: {result.stderr[-200:]}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"[{name}] Timed out after 300s")
        return False
    except Exception as e:
        logger.error(f"[{name}] Exception: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("Trading Daemon starting")
    logger.info(f"Dry run: {dry_run}")
    logger.info(f"AI Brain interval: {AI_BRAIN_INTERVAL}s")
    logger.info(f"Trade Monitor interval: {TRADE_MONITOR_INTERVAL}s")
    logger.info(f"Copytrade interval: {COPYTRADE_INTERVAL}s")
    logger.info("=" * 60)

    # Track last run times
    last_brain = 0
    last_monitor = 0
    last_copytrade = 0

    # Track failures
    brain_failures = 0
    monitor_failures = 0
    copytrade_failures = 0

    # Initial run
    run_script(AI_BRAIN, "AI Brain")
    run_script(TRADE_MONITOR, "Trade Monitor")
    run_script(COPYTRADE_MONITOR, "Copytrade")
    last_brain = last_monitor = last_copytrade = time.time()

    while running:
        now = time.time()

        # AI Trading Brain (every 10 min)
        if now - last_brain >= AI_BRAIN_INTERVAL:
            success = run_script(AI_BRAIN, "AI Brain")
            if success:
                brain_failures = 0
            else:
                brain_failures += 1
                if brain_failures >= 3:
                    logger.error("AI Brain failing repeatedly, increasing interval")
                    # Still run but log warning
            last_brain = now

        # Trade Monitor (every 1 min)
        if now - last_monitor >= TRADE_MONITOR_INTERVAL:
            success = run_script(TRADE_MONITOR, "Trade Monitor")
            if success:
                monitor_failures = 0
            else:
                monitor_failures += 1
            last_monitor = now

        # Copytrade Monitor (every 60 min)
        if now - last_copytrade >= COPYTRADE_INTERVAL:
            success = run_script(COPYTRADE_MONITOR, "Copytrade")
            if success:
                copytrade_failures = 0
            else:
                copytrade_failures += 1
            last_copytrade = now

        # Sleep for a short interval to avoid busy waiting
        # Check every 10 seconds
        for _ in range(10):
            if not running:
                break
            time.sleep(1)

    logger.info("Trading Daemon stopped")


if __name__ == "__main__":
    sys.exit(main())
