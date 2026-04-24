#!/usr/bin/env python3
"""
Trading Daemon - Runs all trading and screener components continuously.

Components:
1. AI Trading Brain - token analysis & trade decisions (every 10 min)
2. Trade Monitor - position monitoring (every 1 min)
3. Copytrade Monitor - smart money tracking (every 60 min)
4. Token Enricher - enriches discovered tokens (every 5 min)
5. Token Discovery - discovers new tokens (every 30 min)

Usage: python3 trading_daemon.py [--dry-run]
"""

import subprocess
import os
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
TOKEN_ENRICHER = SCRIPTS_DIR / "token_enricher.py"
TOKEN_DISCOVERY = SCRIPTS_DIR / "token_discovery.py"

# Intervals (seconds)
AI_BRAIN_INTERVAL = 600  # 10 minutes
TRADE_MONITOR_INTERVAL = 60  # 1 minute
COPYTRADE_INTERVAL = 3600  # 60 minutes
ENRICHER_INTERVAL = 300  # 5 minutes
DISCOVERY_INTERVAL = 1800  # 30 minutes

# State
running = True
dry_run = "--dry-run" in sys.argv


def _cap_log_file(path: str, max_bytes: int = 1_073_741_824, keep_bytes: int = 104_857_600):
    """If log exceeds max_bytes, truncate to keep_bytes from the end."""
    try:
        p = Path(path)
        if p.exists() and p.stat().st_size > max_bytes:
            with open(p, "rb") as f:
                f.seek(-keep_bytes, 2)
                tail = f.read()
            with open(p, "wb") as f:
                f.write(tail)
            logger.info(f"[LogCap] Truncated {path} to last {keep_bytes} bytes")
    except Exception:
        pass


def signal_handler(signum, frame):
    global running
    logger.info(f"Received signal {signum}, shutting down...")
    running = False


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def run_script(
    script_path: Path,
    name: str,
    execute: bool = True,
    use_flock: bool = False,
    timeout: int = 1800,
    log_file: str = None,
    extra_args: list = None,
) -> bool:
    """Run a script and return success status."""
    try:
        cmd = []

        # Add flock if requested (like cron does)
        if use_flock:
            cmd.extend(["flock", "-n", f"/tmp/{script_path.stem}.lock"])

        # Add timeout wrapper
        cmd.extend(["timeout", str(timeout)])
        logger.debug(f"[{name}] Timeout: {timeout}s")

        cmd.append(sys.executable)
        cmd.append(str(script_path))

        # Only ai_trading_brain and trade_monitor take --execute
        if execute and script_path.name in ("ai_trading_brain.py", "trade_monitor.py"):
            cmd.append("--execute")
        if dry_run and script_path.name != "copytrade_monitor.py":
            cmd.append("--dry-run")

        # Append any extra arguments
        if extra_args:
            cmd.extend(extra_args)

        logger.info(f"[{name}] Running...")

        # Set up stdout/stderr
        stdout_dest = subprocess.PIPE
        stderr_dest = subprocess.PIPE

        if log_file:
            # Cap log size before appending
            _cap_log_file(log_file)
            # Redirect to log file (like cron) — force unbuffered so logs appear immediately
            with open(log_file, "a") as log:
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                result = subprocess.run(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout + 10,  # Slightly more than internal timeout
                    env=env,
                )
        else:
            # Capture output for logging
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10,
            )

        if result.returncode == 0:
            logger.info(f"[{name}] Completed successfully")
            if result.stdout and result.stdout.strip():
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
    logger.info(f"Token Enricher interval: {ENRICHER_INTERVAL}s")
    logger.info(f"Token Discovery interval: {DISCOVERY_INTERVAL}s")
    logger.info("=" * 60)

    # Track last run times
    last_brain = 0
    last_monitor = 0
    last_copytrade = 0
    last_enricher = 0
    last_discovery = 0

    # Track failures
    brain_failures = 0
    monitor_failures = 0
    copytrade_failures = 0
    enricher_failures = 0
    discovery_failures = 0

    # Initial run (same args as loop)
    run_script(AI_BRAIN, "AI Brain", execute=True, log_file=str(LOG_DIR / "ai_trading_brain.log"))
    run_script(TRADE_MONITOR, "Trade Monitor", execute=True, timeout=300)
    run_script(COPYTRADE_MONITOR, "Copytrade", timeout=1800)
    run_script(
        TOKEN_ENRICHER,
        "Token Enricher",
        use_flock=True,
        timeout=1800,
        log_file=str(LOG_DIR / "token_screener.log"),
        extra_args=["--async-mode"],
    )
    run_script(TOKEN_DISCOVERY, "Token Discovery", timeout=1800)
    last_brain = last_monitor = last_copytrade = last_enricher = last_discovery = (
        time.time()
    )

    while running:
        now = time.time()

        # AI Trading Brain (every 10 min)
        if now - last_brain >= AI_BRAIN_INTERVAL:
            success = run_script(AI_BRAIN, "AI Brain", log_file=str(LOG_DIR / "ai_trading_brain.log"))
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

        # Token Enricher (every 5 min)
        if now - last_enricher >= ENRICHER_INTERVAL:
            success = run_script(
                TOKEN_ENRICHER,
                "Token Enricher",
                use_flock=True,
                timeout=1800,  # 30 minutes for enrichment pipeline
                log_file=str(LOG_DIR / "token_screener.log"),
                extra_args=["--async-mode"],
            )
            if success:
                enricher_failures = 0
            else:
                enricher_failures += 1
            last_enricher = time.time()

        # Token Discovery (every 30 min)
        if now - last_discovery >= DISCOVERY_INTERVAL:
            success = run_script(
                TOKEN_DISCOVERY,
                "Token Discovery",
                log_file=str(LOG_DIR / "token_discovery.log"),
            )
            if success:
                discovery_failures = 0
            else:
                discovery_failures += 1
            last_discovery = time.time()

        # Sleep for a short interval to avoid busy waiting
        # Check every 10 seconds
        for _ in range(10):
            if not running:
                break
            time.sleep(1)

    logger.info("Trading Daemon stopped")


if __name__ == "__main__":
    sys.exit(main())
