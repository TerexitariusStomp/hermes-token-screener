#!/usr/bin/env python3
"""Forward extracted contract addresses to a central database sink.

Default production mode is local SQLite on this server.
"""
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Tuple
from urllib import error, request

from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')


class CentralContractSink:
    """
    Central contract-address sink with three transport modes:
      - sqlite (default): local DB on this server
      - http: generic ingest endpoint
      - supabase: direct Supabase REST insert
    """

    def __init__(self):
        self.data_dir = Path.home() / '.hermes' / 'data' / 'smart_money'
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.mode = os.getenv('CENTRAL_DB_MODE', 'sqlite').strip().lower()

        self.sqlite_path = Path(
            os.getenv(
                'CENTRAL_DB_SQLITE_PATH',
                str(Path.home() / '.hermes' / 'data' / 'central_contracts.db'),
            )
        )
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        self.queue_path = self.data_dir / 'central_db_queue.jsonl'

        self.central_url = os.getenv('CENTRAL_DB_INGEST_URL', '').strip()
        self.central_bearer = os.getenv('CENTRAL_DB_BEARER_TOKEN', '').strip()

        self.supabase_url = os.getenv('SUPABASE_URL', '').strip().rstrip('/')
        self.supabase_key = (
            os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
            or os.getenv('SUPABASE_ANON_KEY', '').strip()
        )
        self.supabase_table = os.getenv('CENTRAL_DB_TABLE', 'telegram_contract_calls').strip()

        if self.mode == 'sqlite':
            self._ensure_sqlite_schema()

    def enabled(self) -> bool:
        if self.mode == 'sqlite':
            return True
        if self.mode == 'http':
            return bool(self.central_url)
        if self.mode == 'supabase':
            return bool(self.supabase_url and self.supabase_key)
        # fallback: try sqlite if unknown mode
        return True

    def _ensure_sqlite_schema(self):
        conn = sqlite3.connect(self.sqlite_path)
        try:
            conn.execute(
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
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tcc_message_contract
                ON telegram_contract_calls(message_id, contract_address)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tcc_observed_at
                ON telegram_contract_calls(observed_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_contracts_unique (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain TEXT NOT NULL,
                    contract_address TEXT NOT NULL,
                    first_seen_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    mentions INTEGER NOT NULL DEFAULT 1,
                    last_channel_id TEXT,
                    last_message_id INTEGER,
                    last_raw_address TEXT,
                    last_source TEXT,
                    last_message_text TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tcu_chain_contract
                ON telegram_contracts_unique(chain, contract_address)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tcu_last_seen
                ON telegram_contracts_unique(last_seen_at)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _send_sqlite(self, records: List[Dict]) -> Tuple[bool, str]:
        self._ensure_sqlite_schema()
        conn = sqlite3.connect(self.sqlite_path)
        try:
            now = time.time()

            def normalize_contract(chain: str, contract: str):
                if not contract:
                    return None
                c = str(contract).strip()
                ch = (chain or '').lower().strip() or 'unknown'

                # EVM repair + normalization
                if ch in ('ethereum', 'base'):
                    if c.startswith('x') and len(c) == 41:
                        c = '0' + c
                    if c.startswith('0x') and len(c) == 42:
                        hex_part = c[2:]
                        if all(chh in '0123456789abcdefABCDEF' for chh in hex_part):
                            return c.lower()
                    return None

                # Solana base58 validation
                if ch == 'solana':
                    if 32 <= len(c) <= 44 and all(chh in '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz' for chh in c):
                        return c
                    return None

                # Unknown chains: keep conservative minimum length
                return c if len(c) >= 16 else None

            normalized_records = []
            for r in records:
                if r.get('message_id') is None:
                    continue
                chain = r.get('chain')
                normalized = normalize_contract(chain, r.get('contract_address'))
                if not normalized:
                    continue
                normalized_records.append({
                    'channel_id': str(r.get('channel_id', '')),
                    'message_id': int(r.get('message_id', 0)),
                    'chain': (chain or 'unknown').lower(),
                    'contract_address': normalized,
                    'raw_address': r.get('raw_address'),
                    'address_source': r.get('address_source'),
                    'message_text': r.get('message_text'),
                    'observed_at': float(r.get('observed_at', now)),
                    'session_source': r.get('session_source', 'telegram_user_session'),
                })

            rows = [
                (
                    r['channel_id'],
                    r['message_id'],
                    r['chain'],
                    r['contract_address'],
                    r['raw_address'],
                    r['address_source'],
                    r['message_text'],
                    r['observed_at'],
                    r['session_source'],
                    now,
                )
                for r in normalized_records
            ]

            conn.executemany(
                """
                INSERT OR IGNORE INTO telegram_contract_calls (
                    channel_id, message_id, chain, contract_address,
                    raw_address, address_source, message_text,
                    observed_at, session_source, inserted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

            unique_rows = [
                (
                    r['chain'],
                    r['contract_address'],
                    r['observed_at'],
                    r['observed_at'],
                    r['channel_id'],
                    r['message_id'],
                    r['raw_address'],
                    r['address_source'],
                    r['message_text'],
                )
                for r in normalized_records
            ]
            conn.executemany(
                """
                INSERT INTO telegram_contracts_unique (
                    chain, contract_address, first_seen_at, last_seen_at,
                    last_channel_id, last_message_id, last_raw_address,
                    last_source, last_message_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chain, contract_address) DO UPDATE SET
                    mentions = mentions + 1,
                    last_seen_at = excluded.last_seen_at,
                    last_channel_id = excluded.last_channel_id,
                    last_message_id = excluded.last_message_id,
                    last_raw_address = excluded.last_raw_address,
                    last_source = excluded.last_source,
                    last_message_text = excluded.last_message_text
                """,
                unique_rows,
            )

            conn.commit()
            return True, f'sqlite ok rows={len(rows)} unique_upserts={len(unique_rows)} db={self.sqlite_path}'
        except Exception as e:
            return False, f'sqlite error: {e}'
        finally:
            conn.close()

    def _post_json(self, url: str, payload, headers: Dict[str, str], timeout: int = 15) -> Tuple[bool, str]:
        body = json.dumps(payload).encode('utf-8')
        req = request.Request(url, data=body, headers=headers, method='POST')
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, 'status', 200)
                text = resp.read().decode('utf-8', errors='ignore')
                if 200 <= status < 300:
                    return True, text
                return False, f'HTTP {status}: {text[:500]}'
        except error.HTTPError as e:
            text = ''
            try:
                text = e.read().decode('utf-8', errors='ignore')
            except Exception:
                pass
            return False, f'HTTPError {e.code}: {text[:500]}'
        except Exception as e:
            return False, str(e)

    def _send_generic(self, records: List[Dict]) -> Tuple[bool, str]:
        if not self.central_url:
            return False, 'CENTRAL_DB_INGEST_URL not configured'

        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'hermes-smart-money/1.0',
        }
        if self.central_bearer:
            headers['Authorization'] = f'Bearer {self.central_bearer}'

        payload = {
            'source': 'telegram_user_session',
            'records': records,
            'sent_at': time.time(),
        }
        return self._post_json(self.central_url, payload, headers)

    def _send_supabase(self, records: List[Dict]) -> Tuple[bool, str]:
        if not (self.supabase_url and self.supabase_key):
            return False, 'SUPABASE_URL or SUPABASE key not configured'

        url = f"{self.supabase_url}/rest/v1/{self.supabase_table}?on_conflict=message_id,contract_address"
        headers = {
            'Content-Type': 'application/json',
            'apikey': self.supabase_key,
            'Authorization': f'Bearer {self.supabase_key}',
            'Prefer': 'resolution=ignore-duplicates,return=minimal',
        }
        return self._post_json(url, records, headers)

    def _append_to_queue(self, records: List[Dict]):
        with self.queue_path.open('a', encoding='utf-8') as f:
            for row in records:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')

    def _read_queue(self, max_items: int = 1000) -> List[Dict]:
        if not self.queue_path.exists():
            return []
        rows = []
        with self.queue_path.open('r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i >= max_items:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return rows

    def _rewrite_queue_without_prefix(self, drop_count: int):
        if not self.queue_path.exists() or drop_count <= 0:
            return
        with self.queue_path.open('r', encoding='utf-8') as f:
            lines = f.readlines()
        with self.queue_path.open('w', encoding='utf-8') as f:
            f.writelines(lines[drop_count:])

    def _send(self, records: List[Dict]) -> Tuple[bool, str]:
        mode = self.mode
        if mode == 'sqlite':
            return self._send_sqlite(records)
        if mode == 'http':
            return self._send_generic(records)
        if mode == 'supabase':
            return self._send_supabase(records)
        # unknown mode => safe fallback to sqlite
        return self._send_sqlite(records)

    def flush_queue(self, batch_size: int = 300) -> Tuple[int, str]:
        queued = self._read_queue(max_items=batch_size)
        if not queued:
            return 0, 'queue empty'

        ok, msg = self._send(queued)
        if ok:
            self._rewrite_queue_without_prefix(len(queued))
            return len(queued), 'flushed'
        return 0, msg

    def send_records(self, records: List[Dict]) -> Tuple[int, int, str]:
        if not records:
            return 0, 0, 'no records'
        if not self.enabled():
            return 0, len(records), 'central DB sink disabled (missing env config)'

        # best-effort queue flush first
        self.flush_queue()

        ok, msg = self._send(records)
        if ok:
            return len(records), 0, msg

        # queue only for non-sqlite transient failures
        self._append_to_queue(records)
        return 0, len(records), msg
