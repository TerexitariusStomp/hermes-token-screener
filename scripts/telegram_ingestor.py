#!/usr/bin/env python3
"""Telegram message ingestion for call channels with SQLite lock resilience."""
import os
import sys
import asyncio
import time
import json
import sqlite3
from typing import List, Set
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError
from address_extractor import extract_addresses
from smart_money_config import SMART_MONEY_CHANNELS, SMART_MONEY_POLL_INTERVAL, DATA_DIR, LOGS_DIR

# Increase Telethon connection timeout and add retry
SESSION_PATH = Path.home() / '.hermes' / '.telegram_session' / 'hermes_user'
TG_API_ID = int(os.getenv('TG_API_ID', '39533004'))
TG_API_HASH = os.getenv('TG_API_HASH', '958e52889177eec2fa15e9e4e4c2cc4c')

def create_client_with_retry(max_attempts=3):
    """Create TelegramClient with retry on SQLite locking."""
    for attempt in range(1, max_attempts+1):
        try:
            client = TelegramClient(str(SESSION_PATH), TG_API_ID, TG_API_HASH)
            return client
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                print(f"[TelegramIngestor] SQLite lock on client creation (attempt {attempt}/{max_attempts}), waiting...")
                time.sleep(attempt * 2)
                continue
            else:
                raise
    raise RuntimeError("Failed to create TelegramClient after retries")

class TelegramIngestor:
    def __init__(self):
        self.client = None  # lazy creation
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.last_seen_messages: Set[int] = set()
        self.state_file = DATA_DIR / 'telegram_state.json'
        self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.last_seen_messages = set(data.get('last_seen_messages', []))
            except Exception as e:
                print(f"[TelegramIngestor] State load error: {e}")

    def _save_state(self):
        try:
            self.state_file.write_text(json.dumps({'last_seen_messages': list(self.last_seen_messages)}))
        except Exception as e:
            print(f"[TelegramIngestor] State save error: {e}")

    def start(self):
        """Initialize and connect with retry logic."""
        # Create client with lock retry
        try:
            self.client = create_client_with_retry()
        except Exception as e:
            print(f"[TelegramIngestor] Failed to create client: {e}")
            return False

        # Connect with retry
        max_attempts = 3
        for attempt in range(1, max_attempts+1):
            try:
                self._loop.run_until_complete(self._connect())
                return True
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    print(f"[TelegramIngestor] SQLite lock on connect (attempt {attempt}/{max_attempts}), retrying...")
                    time.sleep(attempt * 2)
                    continue
                else:
                    raise
            except Exception as e:
                print(f"[TelegramIngestor] Connection error: {e}")
                return False
        return False

    async def _connect(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            print("[TelegramIngestor] User session not authorized. Run telegram_user.py first.")
            return False
        print(f"[TelegramIngestor] Connected. Monitoring {len(SMART_MONEY_CHANNELS)} channels.")
        return True

    def poll_channels(self) -> List[dict]:
        """Poll configured channels for new messages."""
        if not self.client:
            print("[TelegramIngestor] Client not initialized")
            return []

        try:
            extractions = []
            for channel_id_str in SMART_MONEY_CHANNELS:
                try:
                    channel_id = int(channel_id_str)
                except ValueError:
                    channel_id = channel_id_str

                try:
                    messages = self._loop.run_until_complete(
                        self.client.get_messages(channel_id, limit=20)
                    )
                    for msg in messages:
                        if msg.id in self.last_seen_messages:
                            continue
                        self.last_seen_messages.add(msg.id)
                        if not msg.text:
                            continue
                        token_addrs = extract_addresses(msg.text)
                        if token_addrs:
                            extractions.append({
                                'channel_id': channel_id,
                                'message_id': msg.id,
                                'text': msg.text[:500],
                                'timestamp': time.time(),
                                'token_addresses': token_addrs
                            })
                except Exception as e:
                    print(f"[TelegramIngestor] Error polling {channel_id}: {e}")

            # Prune old message IDs (keep last 2000)
            if len(self.last_seen_messages) > 2000:
                self.last_seen_messages = set(list(self.last_seen_messages)[-2000:])
            self._save_state()
            return extractions
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                print("[TelegramIngestor] SQLite lock during polling - will retry next cycle")
                return []
            raise

    def stop(self):
        if self.client:
            try:
                self._loop.run_until_complete(self.client.disconnect())
            except:
                pass

def test_ingestor():
    """Simple connection test."""
    from dotenv import load_dotenv
    load_dotenv(Path.home() / '.hermes' / '.env')

    ingestor = TelegramIngestor()
    if ingestor.start():
        print("[TEST] Ingestor started successfully")
        results = ingestor.poll_channels()
        print(f"[TEST] Found {len(results)} messages with token addresses")
        ingestor.stop()
    else:
        print("[TEST] Ingestor failed to start")

if __name__ == '__main__':
    test_ingestor()
