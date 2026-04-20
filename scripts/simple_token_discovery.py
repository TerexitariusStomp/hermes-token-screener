#!/usr/bin/env python3
"""
Simplified Token Address Discovery Script
Focuses on getting token addresses from Rick Burp Bot responses.
"""

import asyncio
import re
import sqlite3
import sys
from pathlib import Path

# Add the scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import the Telegram client
from telethon import TelegramClient
from token_discovery_shared import (
    ensure_discovered_tokens_table,
    insert_discovered_token,
    lookup_token_address,
)

from hermes_screener.config import settings

# Configuration
SESSION_PATH = settings.session_path
TG_API_ID = settings.tg_api_id
TG_API_HASH = settings.tg_api_hash
DB_PATH = settings.db_path


class SimpleTokenDiscovery:
    """Simplified token discovery focusing on getting addresses."""

    def __init__(self):
        self.client = None
        self.channel = None
        self.db_conn = None

    def get_token_address_from_name(self, token_name: str) -> dict:
        """Get token address from token name using DexScreener API."""
        return lookup_token_address(token_name)

    async def get_trending_tokens(self) -> list[str]:
        """Get trending token names from Rick Burp Bot."""
        token_names = []

        # Connect to Telegram
        self.client = TelegramClient(str(SESSION_PATH), TG_API_ID, TG_API_HASH)
        await self.client.connect()

        if not await self.client.is_user_authorized():
            print("Not authorized. Please run telegram_user.py interactively first.")
            return token_names

        print("Connected to Telegram!")

        # Find the RickBurp channel
        async for dialog in self.client.iter_dialogs():
            if hasattr(dialog.entity, "title") and "rickburp" in dialog.entity.title.lower():
                self.channel = dialog.entity
                print(f"Found channel: {self.channel.title} (ID: {self.channel.id})")
                break

        if not self.channel:
            print("Could not find RickBurp channel")
            return token_names

        # Get trending tokens from /dt command
        print("\n=== Getting trending tokens from /dt ===")
        try:
            await self.client.send_message(self.channel, "/dt@rick")
            await asyncio.sleep(3)

            messages = await self.client.get_messages(self.channel, limit=5)
            for msg in messages:
                if msg.message and "Trending DEX tokens" in msg.message:
                    # Extract token names
                    token_pattern = re.compile(r"([A-Za-z0-9]+) @")
                    matches = token_pattern.findall(msg.message)
                    token_names.extend(matches)
                    print(f"Found {len(matches)} trending tokens")
                    break
        except Exception as e:
            print(f"Error getting trending tokens: {e}")

        # Also get from /pft command
        print("\n=== Getting trending Pump tokens from /pft ===")
        try:
            await self.client.send_message(self.channel, "/pft@rick")
            await asyncio.sleep(3)

            messages = await self.client.get_messages(self.channel, limit=5)
            for msg in messages:
                if msg.message and "Trending Pump tokens" in msg.message:
                    # Extract token names
                    token_pattern = re.compile(r"([A-Za-z0-9]+) @")
                    matches = token_pattern.findall(msg.message)
                    token_names.extend(matches)
                    print(f"Found {len(matches)} trending Pump tokens")
                    break
        except Exception as e:
            print(f"Error getting trending Pump tokens: {e}")

        await self.client.disconnect()
        return list(set(token_names))  # Remove duplicates

    def init_database(self):
        """Initialize database for storing token information."""
        self.db_conn = sqlite3.connect(DB_PATH)
        ensure_discovered_tokens_table(self.db_conn)
        print("Database initialized")

    def store_token(self, token_info: dict, discovery_method: str = "rick_bot"):
        """Store token information in database."""
        insert_discovered_token(self.db_conn, token_info, discovery_method)

    async def run(self):
        """Run the simplified token discovery."""
        print("Starting Simplified Token Discovery...")
        print("=" * 60)

        # Initialize database
        self.init_database()

        # Get trending token names
        token_names = await self.get_trending_tokens()

        if not token_names:
            print("No token names found")
            return

        print(f"\n=== Processing {len(token_names)} tokens ===")

        # Get addresses for each token
        discovered_tokens = []
        for i, token_name in enumerate(token_names[:20]):  # Limit to 20 tokens
            print(f"\n{i+1}/{min(20, len(token_names))}: Processing {token_name}...")

            # Get address from DexScreener
            token_info = self.get_token_address_from_name(token_name)

            if token_info["address"]:
                print(f"  Found address: {token_info['address'][:20]}...")
                print(f"  Chain: {token_info['chain']}")
                print(f"  DEX: {token_info.get('dex', 'N/A')}")
                print(f"  Price: {token_info.get('price', 'N/A')}")
                print(f"  Liquidity: {token_info.get('liquidity', 'N/A')}")

                # Store in database
                self.store_token(token_info)
                discovered_tokens.append(token_info)
            else:
                print("  No address found")

            # Small delay to avoid rate limits
            if i < len(token_names) - 1:
                await asyncio.sleep(0.5)

        # Print summary
        print("\n" + "=" * 60)
        print("DISCOVERY SUMMARY")
        print("=" * 60)
        print(f"Total tokens processed: {min(20, len(token_names))}")
        print(f"Tokens with addresses: {len(discovered_tokens)}")
        print(f"Addresses saved to database: {DB_PATH}")

        # Print discovered tokens
        if discovered_tokens:
            print("\nDiscovered Tokens:")
            for i, token in enumerate(discovered_tokens, 1):
                print(f"{i:2d}. {token['name']:15} | {token['address'][:20]}... | {token.get('chain', 'N/A')}")

        # Close database
        if self.db_conn:
            self.db_conn.close()

        return discovered_tokens


async def main():
    """Main entry point."""
    discovery = SimpleTokenDiscovery()
    await discovery.run()


if __name__ == "__main__":
    asyncio.run(main())
