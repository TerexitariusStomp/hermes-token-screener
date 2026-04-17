#!/usr/bin/env python3
"""
Telegram Contract Address Scraper
Enumerates all dialogs from user session and extracts contract addresses.
Self-contained: inlines address extraction (no external deps beyond stdlib + telethon).

Usage:
  python3 telegram_scraper.py              # normal run
  python3 telegram_scraper.py --max-dialogs 50  # limit dialogs
  python3 telegram_scraper.py --dry-run    # test without DB writes

Output: central_contracts.db (telegram_contract_calls + telegram_contracts_unique)
"""

import asyncio
import json
import re
import sqlite3
import sys
import time

try:
    from telethon import TelegramClient
    from telethon.tl.types import Channel, Chat, User
except ImportError:
    print("ERROR: telethon not installed. pip install telethon")
    sys.exit(1)

from hermes_screener.config import settings
from hermes_screener.logging import get_logger
from hermes_screener.metrics import start_metrics_server

# ── Config (from centralized settings + scraper-specific defaults) ───────────
SESSION_PATH = settings.session_path
TG_API_ID = settings.tg_api_id
TG_API_HASH = settings.tg_api_hash
DB_PATH = settings.db_path
STATE_FILE = settings.state_file

MESSAGES_PER_DIALOG = 30
MAX_DIALOGS_PER_CYCLE = 200
MIN_CYCLE_INTERVAL = 60
SESSION_SOURCE = "tg_contract_scraper"
INCLUDE_BOTS = False

# ── Logging + Metrics ────────────────────────────────────────────────────────
log = get_logger("telegram_scraper")
start_metrics_server()

# ── Address Extraction (inlined) ────────────────────────────────────────────
EVM_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}")
SOLANA_PATTERN = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
XRPL_PATTERN = re.compile(r"r[1-9A-HJ-NP-Za-km-z]{24,34}")
DEX_LINK_PATTERN = re.compile(
    r"(?:dexscreener\.com|gmgn\.ai|raydium\.io|pump\.fun)/[^\s)]+"
)
PUMP_FUN_RE = re.compile(r"/([a-fA-F0-9]+)")


def extract_addresses(text: str) -> list[tuple[str, str, str]]:
    """
    Extract token addresses from text.
    Returns list of (original, normalized_address, source_hint) tuples.
    Priority: DEX links > raw addresses (avoids double-counting).
    """
    results = []

    # 1. Extract from DEX links first (higher confidence)
    for link in DEX_LINK_PATTERN.findall(text):
        if "dexscreener.com" in link:
            m = EVM_PATTERN.search(link)
            if m:
                results.append((link, m.group(0).lower(), "dexscreener_link"))
        elif "gmgn.ai" in link:
            m = EVM_PATTERN.search(link)
            if m:
                results.append((link, m.group(0).lower(), "gmgn_link"))
            else:
                m = SOLANA_PATTERN.search(link)
                if m:
                    results.append((link, m.group(0), "gmgn_link"))
        elif "pump.fun" in link:
            m = PUMP_FUN_RE.search(link)
            if m:
                results.append((link, m.group(1), "pump_fun_link"))

    # 2. Raw EVM addresses
    seen = {r[1] for r in results}
    for match in EVM_PATTERN.findall(text):
        norm = match.lower()
        if norm not in seen:
            results.append((match, norm, "evm_raw"))
            seen.add(norm)

    # 3. Raw Solana addresses (base58, 32-44 chars)
    base58_chars = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    for match in SOLANA_PATTERN.findall(text):
        if len(match) >= 32 and all(c in base58_chars for c in match):
            if match not in seen:
                results.append((match, match, "solana_raw"))
                seen.add(match)

    # 4. XRPL addresses (r-prefixed, 25-35 chars)
    for match in XRPL_PATTERN.findall(text):
        if match not in seen:
            results.append((match, match, "xrpl_raw"))
            seen.add(match)

    return results


# ── State Management ────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_seen_per_chat": {}, "last_run": 0, "known_dialogs": []}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Database ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_tables(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS telegram_contract_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            chain TEXT,
            contract_address TEXT NOT NULL,
            raw_address TEXT,
            address_source TEXT,
            message_text TEXT,
            observed_at REAL,
            session_source TEXT,
            inserted_at REAL NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_calls_msg_contract
            ON telegram_contract_calls(message_id, contract_address);

        CREATE TABLE IF NOT EXISTS telegram_contracts_unique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain TEXT NOT NULL,
            contract_address TEXT NOT NULL,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            mentions INTEGER NOT NULL,
            last_channel_id TEXT,
            last_message_id INTEGER,
            last_raw_address TEXT,
            last_source TEXT,
            last_message_text TEXT,
            channel_count INTEGER NOT NULL DEFAULT 0,
            channels_seen TEXT DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_chain_addr
            ON telegram_contracts_unique(chain, contract_address);
    """
    )
    conn.commit()


def insert_extraction(
    conn,
    channel_id: str,
    message_id: int,
    chain: str,
    contract_address: str,
    raw_address: str,
    source: str,
    message_text: str,
    observed_at: float,
    dry_run: bool = False,
) -> bool:
    now = time.time()
    if dry_run:
        return True

    try:
        conn.execute(
            """
            INSERT INTO telegram_contract_calls
                (channel_id, message_id, chain, contract_address, raw_address,
                 address_source, message_text, observed_at, session_source, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                str(channel_id),
                message_id,
                chain,
                contract_address,
                raw_address,
                source,
                message_text[:500] if message_text else "",
                observed_at,
                SESSION_SOURCE,
                now,
            ),
        )

        chan_str = str(channel_id)
        conn.execute(
            """
            INSERT INTO telegram_contracts_unique
                (chain, contract_address, first_seen_at, last_seen_at, mentions,
                 last_channel_id, last_message_id, last_raw_address, last_source,
                 last_message_text, channel_count, channels_seen)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(chain, contract_address) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                mentions = mentions + 1,
                last_channel_id = excluded.last_channel_id,
                last_message_id = excluded.last_message_id,
                last_raw_address = excluded.last_raw_address,
                last_source = excluded.last_source,
                last_message_text = excluded.last_message_text,
                channel_count = CASE
                    WHEN ',' || channels_seen || ',' LIKE '%,' || ? || ',%'
                    THEN channel_count
                    ELSE channel_count + 1
                END,
                channels_seen = CASE
                    WHEN channels_seen = '' OR channels_seen IS NULL THEN ?
                    WHEN ',' || channels_seen || ',' LIKE '%,' || ? || ',%'
                    THEN channels_seen
                    ELSE channels_seen || ',' || ?
                END
        """,
            (
                chain,
                contract_address,
                now,
                now,
                chan_str,
                message_id,
                raw_address,
                source,
                message_text[:500] if message_text else "",
                chan_str,
                chan_str,
                chan_str,
                chan_str,
                chan_str,
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        log.error(f"DB insert error: {e}")
        return False


# ── Telegram ────────────────────────────────────────────────────────────────
def create_client_with_retry(max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        try:
            return TelegramClient(str(SESSION_PATH), TG_API_ID, TG_API_HASH)
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                log.warning(
                    f"SQLite lock on client creation (attempt {attempt}/{max_attempts})"
                )
                time.sleep(attempt * 2)
            else:
                raise
    raise RuntimeError("Failed to create TelegramClient after retries")


async def get_all_dialogs(client) -> list:
    dialogs = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            dialogs.append(dialog)
        elif isinstance(entity, User) and entity.bot:
            if INCLUDE_BOTS:
                dialogs.append(dialog)
    return dialogs


async def poll_dialog(
    client, dialog, last_seen: dict, conn, dry_run: bool = False
) -> int:
    chat_id = dialog.id
    chat_title = getattr(dialog.entity, "title", None) or str(chat_id)
    last_id = last_seen.get(str(chat_id), 0)

    new_count = 0
    max_id_seen = last_id
    try:
        messages = await client.get_messages(dialog.entity, limit=MESSAGES_PER_DIALOG)
    except Exception as e:
        log.warning(f"Failed to get messages from {chat_title}: {e}")
        return 0

    for msg in messages:
        if msg.id <= last_id:
            continue
        if not msg.text:
            continue
        if msg.id > max_id_seen:
            max_id_seen = msg.id

        for orig, normalized, source in extract_addresses(msg.text):
            chain = (
                "solana"
                if not normalized.startswith("0x") and not normalized.startswith("r")
                else "xrpl"
                if normalized.startswith("r")
                else "ethereum"
            )
            inserted = insert_extraction(
                conn,
                channel_id=str(chat_id),
                message_id=msg.id,
                chain=chain,
                contract_address=normalized,
                raw_address=orig,
                source=source,
                message_text=msg.text,
                observed_at=msg.date.timestamp() if msg.date else time.time(),
                dry_run=dry_run,
            )
            if inserted:
                new_count += 1

    if max_id_seen > last_id:
        last_seen[str(chat_id)] = max_id_seen
    return new_count


async def run_scrape(max_dialogs: int = None, dry_run: bool = False):
    state = load_state()
    last_seen = state.get("last_seen_per_chat", {})

    now = time.time()
    last_run = state.get("last_run", 0)
    if not dry_run and now - last_run < MIN_CYCLE_INTERVAL:
        elapsed = now - last_run
        log.info(
            f"Skipping - only {elapsed:.0f}s since last run (min {MIN_CYCLE_INTERVAL}s)"
        )
        return {"status": "skipped", "reason": "rate_limit", "elapsed": elapsed}

    log.info("Connecting to Telegram...")
    client = create_client_with_retry()
    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.error("Session not authorized. Authenticate your Telegram session first (Telethon login required).")
            return {"status": "error", "reason": "not_authorized"}

        log.info("Fetching all dialogs...")
        dialogs = await get_all_dialogs(client)
        log.info(f"Found {len(dialogs)} group/channel dialogs")

        max_d = max_dialogs or MAX_DIALOGS_PER_CYCLE
        if len(dialogs) > max_d:
            dialogs = dialogs[:max_d]
            log.info(f"Limited to {max_d} most active dialogs")

        conn = get_db()
        ensure_tables(conn)
        total_new = 0
        total_polls = 0
        chat_stats = {}

        for i, dialog in enumerate(dialogs):
            try:
                new_in_chat = await poll_dialog(
                    client, dialog, last_seen, conn, dry_run
                )
                total_new += new_in_chat
                total_polls += 1
                if new_in_chat > 0:
                    chat_name = getattr(dialog.entity, "title", None) or str(dialog.id)
                    chat_stats[chat_name] = new_in_chat

                if (i + 1) % 10 == 0:
                    conn.commit()
            except Exception as e:
                log.error(f"Error polling dialog {dialog.id}: {e}")
                continue

        conn.commit()
        conn.close()

        if not dry_run:
            state["last_seen_per_chat"] = {k: v for k, v in last_seen.items() if v > 0}
            state["last_run"] = now
            state["known_dialogs"] = [d.id for d in dialogs]
            save_state(state)

        log.info(
            f"Cycle complete: {total_new} new contracts from {total_polls} dialogs"
        )
        if chat_stats:
            top = sorted(chat_stats.items(), key=lambda x: -x[1])[:5]
            log.info(f"Top chats: {', '.join(f'{n}({c})' for n, c in top)}")

        return {
            "status": "ok",
            "dialogs_polled": total_polls,
            "new_contracts": total_new,
            "top_chats": dict(
                list(sorted(chat_stats.items(), key=lambda x: -x[1]))[:10]
            ),
            "dry_run": dry_run,
        }

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Telegram contract address scraper")
    parser.add_argument("--max-dialogs", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("Telegram Contract Scraper starting")
    log.info(f"DB: {DB_PATH}")
    log.info(f"Max dialogs/cycle: {args.max_dialogs or MAX_DIALOGS_PER_CYCLE}")
    log.info(f"Messages/dialog: {MESSAGES_PER_DIALOG}")
    if args.dry_run:
        log.info("*** DRY RUN - no DB writes ***")
    log.info("=" * 60)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(run_scrape(args.max_dialogs, args.dry_run))
        log.info(f"Result: {json.dumps(result, indent=2)}")
        return 0 if result.get("status") in ("ok", "skipped") else 1
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        return 1
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
