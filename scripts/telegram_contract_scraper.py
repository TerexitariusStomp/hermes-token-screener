#!/usr/bin/env python3
"""
Telegram Contract Address Scraper - Broad Coverage
Enumerates ALL dialogs from the user session and extracts contract addresses.
Writes to the same central_contracts.db as the existing smart-money system.
"""

import os
import sys
import asyncio
import time
import json
import sqlite3
import logging
from pathlib import Path
from typing import List, Set, Optional
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User

# Add scripts dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from address_extractor import extract_addresses

# ── Config ──────────────────────────────────────────────────────────────────
SESSION_PATH = Path.home() / '.hermes' / '.telegram_session' / 'hermes_user'
TG_API_ID = int(os.getenv('TG_API_ID', '39533004'))
TG_API_HASH = os.getenv('TG_API_HASH', '958e52889177eec2fa15e9e4e4c2cc4c')

DB_PATH = Path(os.getenv('CENTRAL_DB_SQLITE_PATH',
             str(Path.home() / '.hermes' / 'data' / 'central_contracts.db')))
STATE_FILE = Path.home() / '.hermes' / 'data' / 'tg_scraper_state.json'
LOG_FILE = Path.home() / '.hermes' / 'logs' / 'tg_contract_scraper.log'

# How many messages to fetch per dialog per cycle
MESSAGES_PER_DIALOG = int(os.getenv('SCRAPER_MSGS_PER_DIALOG', '30'))
# Max dialogs to poll per cycle (rate-limit protection)
MAX_DIALOGS_PER_CYCLE = int(os.getenv('SCRAPER_MAX_DIALOGS', '200'))
# Minimum seconds between cycles
MIN_CYCLE_INTERVAL = int(os.getenv('SCRAPER_MIN_INTERVAL', '60'))
# Session source tag
SESSION_SOURCE = os.getenv('SCRAPER_SESSION_SOURCE', 'tg_contract_scraper')
# Chat types to include
INCLUDE_BOTS = os.getenv('SCRAPER_INCLUDE_BOTS', 'false').lower() == 'true'

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('tg_scraper')

# ── State Management ────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            pass
    return {'last_seen_per_chat': {}, 'last_run': 0, 'known_dialogs': []}

def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── Database ────────────────────────────────────────────────────────────────
def get_db():
    """Get SQLite connection with WAL mode for concurrent access."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def ensure_tables(conn):
    """Create tables if they don't exist (idempotent)."""
    conn.executescript("""
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
    """)
    conn.commit()

def insert_extraction(conn, channel_id: str, message_id: int,
                      chain: str, contract_address: str, raw_address: str,
                      source: str, message_text: str, observed_at: float) -> bool:
    """Insert a single contract extraction. Returns True if new."""
    now = time.time()
    try:
        # Insert into calls table (deduped by message_id + contract_address)
        conn.execute("""
            INSERT INTO telegram_contract_calls
                (channel_id, message_id, chain, contract_address, raw_address,
                 address_source, message_text, observed_at, session_source, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(channel_id), message_id, chain, contract_address, raw_address,
              source, message_text[:500] if message_text else '', observed_at,
              SESSION_SOURCE, now))

        # Upsert into unique table with channel tracking
        chan_str = str(channel_id)
        params = (chain, contract_address, now, now, chan_str, message_id,
                  raw_address, source, message_text[:500] if message_text else '',
                  chan_str,         # INSERT: channels_seen (initial value)
                  chan_str,         # CASE channel_count check
                  chan_str,         # channels_seen empty case
                  chan_str,         # channels_seen already-has check
                  chan_str)         # channels_seen append
        conn.execute("""
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
        """, params)
        return True
    except sqlite3.IntegrityError:
        return False  # Already exists (deduped)
    except Exception as e:
        log.error(f"DB insert error: {e}")
        return False

# ── Telegram ────────────────────────────────────────────────────────────────
def create_client_with_retry(max_attempts=3):
    """Create TelegramClient with SQLite lock retry."""
    for attempt in range(1, max_attempts + 1):
        try:
            client = TelegramClient(str(SESSION_PATH), TG_API_ID, TG_API_HASH)
            return client
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                log.warning(f"SQLite lock on client creation (attempt {attempt}/{max_attempts})")
                time.sleep(attempt * 2)
            else:
                raise
    raise RuntimeError("Failed to create TelegramClient after retries")

async def get_all_dialogs(client) -> list:
    """Get all dialogs filtered to groups, channels, and supergroups."""
    dialogs = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        # Include: groups, supergroups, channels, megagroups
        # Exclude: private DMs (User) unless bot
        if isinstance(entity, (Channel, Chat)):
            dialogs.append(dialog)
        elif isinstance(entity, User) and entity.bot:
            if INCLUDE_BOTS:
                dialogs.append(dialog)
    return dialogs

async def poll_dialog(client, dialog, last_seen: dict, conn) -> int:
    """Poll a single dialog for contract addresses. Returns count of new extractions."""
    chat_id = dialog.id
    chat_title = getattr(dialog.entity, 'title', None) or str(chat_id)
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

        token_addrs = extract_addresses(msg.text)
        if not token_addrs:
            continue

        for orig, normalized, source in token_addrs:
            chain = 'solana' if not normalized.startswith('0x') else 'ethereum'
            inserted = insert_extraction(
                conn,
                channel_id=str(chat_id),
                message_id=msg.id,
                chain=chain,
                contract_address=normalized,
                raw_address=orig,
                source=source,
                message_text=msg.text,
                observed_at=msg.date.timestamp() if msg.date else time.time()
            )
            if inserted:
                new_count += 1

    # Update last seen
    if max_id_seen > last_id:
        last_seen[str(chat_id)] = max_id_seen

    return new_count

async def run_scrape():
    """Main scrape loop."""
    state = load_state()
    last_seen = state.get('last_seen_per_chat', {})

    # Rate limit check
    now = time.time()
    last_run = state.get('last_run', 0)
    if now - last_run < MIN_CYCLE_INTERVAL:
        elapsed = now - last_run
        log.info(f"Skipping - only {elapsed:.0f}s since last run (min {MIN_CYCLE_INTERVAL}s)")
        return {'status': 'skipped', 'reason': 'rate_limit', 'elapsed': elapsed}

    log.info("Connecting to Telegram...")
    client = create_client_with_retry()
    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.error("Session not authorized. Run telegram_user.py first.")
            return {'status': 'error', 'reason': 'not_authorized'}

        log.info("Fetching all dialogs...")
        dialogs = await get_all_dialogs(client)
        log.info(f"Found {len(dialogs)} group/channel dialogs")

        # Limit to MAX_DIALOGS_PER_CYCLE (prioritize by most recent activity)
        if len(dialogs) > MAX_DIALOGS_PER_CYCLE:
            dialogs = dialogs[:MAX_DIALOGS_PER_CYCLE]
            log.info(f"Limited to {MAX_DIALOGS_PER_CYCLE} most active dialogs")

        # Poll each dialog
        conn = get_db()
        ensure_tables(conn)
        total_new = 0
        total_polls = 0
        chat_stats = {}

        for i, dialog in enumerate(dialogs):
            try:
                new_in_chat = await poll_dialog(client, dialog, last_seen, conn)
                total_new += new_in_chat
                total_polls += 1
                if new_in_chat > 0:
                    chat_name = getattr(dialog.entity, 'title', None) or str(dialog.id)
                    chat_stats[chat_name] = new_in_chat

                # Commit every 10 dialogs for resilience
                if (i + 1) % 10 == 0:
                    conn.commit()
                    log.debug(f"Committed after {i + 1} dialogs ({total_new} new so far)")

            except Exception as e:
                log.error(f"Error polling dialog {dialog.id}: {e}")
                continue

        conn.commit()
        conn.close()

        # Save state
        state['last_seen_per_chat'] = {k: v for k, v in last_seen.items() if v > 0}
        state['last_run'] = now
        state['known_dialogs'] = [d.id for d in dialogs]
        save_state(state)

        log.info(f"Cycle complete: {total_new} new contracts from {total_polls} dialogs")
        if chat_stats:
            top = sorted(chat_stats.items(), key=lambda x: -x[1])[:5]
            log.info(f"Top chats: {', '.join(f'{n}({c})' for n, c in top)}")

        return {
            'status': 'ok',
            'dialogs_polled': total_polls,
            'new_contracts': total_new,
            'top_chats': dict(list(sorted(chat_stats.items(), key=lambda x: -x[1]))[:10])
        }

    finally:
        try:
            await client.disconnect()
        except:
            pass

def main():
    """Entry point."""
    log.info("=" * 60)
    log.info("Telegram Contract Scraper starting")
    log.info(f"DB: {DB_PATH}")
    log.info(f"Max dialogs/cycle: {MAX_DIALOGS_PER_CYCLE}")
    log.info(f"Messages/dialog: {MESSAGES_PER_DIALOG}")
    log.info("=" * 60)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(run_scrape())
        log.info(f"Result: {json.dumps(result, indent=2)}")
        return 0 if result.get('status') == 'ok' else 1
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        return 1
    finally:
        loop.close()

if __name__ == '__main__':
    sys.exit(main())
