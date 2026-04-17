#!/usr/bin/env python3
"""
Enhanced Token Address Discovery Script
Combines Rick Burp Bot data with DexScreener API for maximum token coverage.
"""

import asyncio
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add the scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import the Telegram client
from telethon import TelegramClient

from token_discovery_shared import (
    ensure_discovered_tokens_table,
    insert_discovered_token,
    lookup_token_address,
)

# Configuration
SESSION_PATH = Path.home() / ".hermes" / ".telegram_session" / "hermes_user"
TG_API_ID = int(os.getenv("TG_API_ID", "39533004"))
TG_API_HASH = os.getenv("TG_API_HASH", "958e52889177eec2fa15e9e4e4c2cc4c")
DB_PATH = Path.home() / ".hermes" / "call_channels.db"

# Bot commands to execute for maximum token coverage
BOT_COMMANDS = [
    ("/dt", "Trending DEX tokens"),
    ("/pft", "Trending Pump tokens"),
    ("/runners", "Runners report (tokens over 100K)"),
    ("/burp", "Best plays from last hour"),
    ("/hot", "Popular tokens in current chat"),
]


class EnhancedTokenDiscovery:
    """Enhanced token discovery combining bot data with API enrichment."""

    def __init__(self):
        self.client = None
        self.channel = None
        self.db_conn = None
        self.discovered_tokens = []

    def get_token_address_from_name(self, token_name: str) -> Dict:
        """Get token address from token name using DexScreener API."""
        return lookup_token_address(token_name)

    async def connect(self):
        """Connect to Telegram and find the RickBurp channel."""
        self.client = TelegramClient(str(SESSION_PATH), TG_API_ID, TG_API_HASH)
        await self.client.connect()

        if not await self.client.is_user_authorized():
            raise Exception("Not authorized. Run telegram_user.py interactively first.")

        print("Connected to Telegram!")

        # Find the RickBurp channel
        async for dialog in self.client.iter_dialogs():
            if (
                hasattr(dialog.entity, "title")
                and "rickburp" in dialog.entity.title.lower()
            ):
                self.channel = dialog.entity
                print(f"Found channel: {self.channel.title} (ID: {self.channel.id})")
                break

        if not self.channel:
            raise Exception("Could not find RickBurp channel")

    def init_database(self):
        """Initialize database for storing token information."""
        self.db_conn = sqlite3.connect(DB_PATH)
        ensure_discovered_tokens_table(self.db_conn)
        print("Database initialized")

    def store_token(self, token_info: Dict, discovery_method: str = "rick_bot"):
        """Store token information in database."""
        insert_discovered_token(self.db_conn, token_info, discovery_method)

    async def send_command(self, command: str, description: str) -> Optional[str]:
        """Send a command to the bot and return the response."""
        try:
            print(f"  Sending command: {command} ({description})")

            # Get messages before sending command
            messages_before = await self.client.get_messages(self.channel, limit=1)
            last_msg_id_before = messages_before[0].id if messages_before else 0

            # Send command
            await self.client.send_message(self.channel, f"{command}@rick")

            # Wait for response
            await asyncio.sleep(4)

            # Get new messages after our command
            messages_after = await self.client.get_messages(self.channel, limit=10)

            # Find the bot's response
            bot_response = None
            for msg in messages_after:
                if msg.id > last_msg_id_before and msg.message:
                    # Check if this is from the bot (Rick)
                    if (
                        msg.sender_id
                        and msg.sender_id != (await self.client.get_me()).id
                    ):
                        # This is likely the bot's response
                        bot_response = msg.message
                        break

            if not bot_response:
                # Fallback: look for any message with relevant keywords
                for msg in messages_after:
                    if msg.message and len(msg.message) > 50:
                        if any(
                            keyword in msg.message.lower()
                            for keyword in [
                                "trending",
                                "best",
                                "runners",
                                "popular",
                                "hot",
                            ]
                        ):
                            bot_response = msg.message
                            break

            return bot_response

        except Exception as e:
            print(f"Error sending command {command}: {e}")
            return None

    def extract_token_names(self, response: str) -> List[str]:
        """Extract token names from bot response."""
        token_names = []

        # Look for token names in various formats
        patterns = [
            r"([A-Za-z0-9]+) @",  # Format: "TOKENNAME @ ..."
            r"🥇 ([A-Za-z0-9]+)",  # Format: "🥇 TOKENNAME"
            r"🥈 ([A-Za-z0-9]+)",  # Format: "🥈 TOKENNAME"
            r"🥉 ([A-Za-z0-9]+)",  # Format: "🥉 TOKENNAME"
            r"4️⃣ ([A-Za-z0-9]+)",  # Format: "4️⃣ TOKENNAME"
            r"5️⃣ ([A-Za-z0-9]+)",  # Format: "5️⃣ TOKENNAME"
        ]

        for pattern in patterns:
            matches = re.findall(pattern, response)
            token_names.extend(matches)

        # Remove duplicates and filter out common words
        common_words = {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "have",
            "been",
            "will",
            "your",
            "more",
        }
        filtered_names = []
        for name in token_names:
            if len(name) >= 3 and name.lower() not in common_words:
                filtered_names.append(name)

        return list(set(filtered_names))

    async def collect_data(self):
        """Collect data from all bot commands."""
        print("\n=== Collecting data from Rick Burp Bot ===")

        all_token_names = []

        # Execute each command
        for command, description in BOT_COMMANDS:
            response = await self.send_command(command, description)
            if response:
                # Extract token names
                token_names = self.extract_token_names(response)
                all_token_names.extend(token_names)
                print(f"    Found {len(token_names)} token names")

            # Wait between commands
            await asyncio.sleep(1)

        # Remove duplicates
        unique_token_names = list(set(all_token_names))
        print(f"\nTotal unique token names found: {len(unique_token_names)}")

        return unique_token_names

    async def enrich_tokens(self, token_names: List[str]):
        """Enrich token names with addresses and details."""
        print(f"\n=== Enriching {len(token_names)} tokens with addresses ===")

        # Limit to 30 tokens to avoid timeouts
        tokens_to_process = token_names[:30]

        for i, token_name in enumerate(tokens_to_process):
            print(f"\n{i+1}/{len(tokens_to_process)}: Processing {token_name}...")

            # Get address from DexScreener
            token_info = self.get_token_address_from_name(token_name)

            if token_info["address"]:
                print(f"  Found address: {token_info['address'][:20]}...")
                print(f"  Chain: {token_info['chain']}")
                print(f"  DEX: {token_info.get('dex', 'N/A')}")
                print(f"  Price: {token_info.get('price', 'N/A')}")
                print(f"  Liquidity: {token_info.get('liquidity', 'N/A')}")

                # Store in database
                self.store_token(token_info, "rick_bot_enriched")
                self.discovered_tokens.append(token_info)
            else:
                print(f"  No address found")

            # Small delay to avoid rate limits
            if i < len(tokens_to_process) - 1:
                await asyncio.sleep(0.5)

        print(
            f"\nSuccessfully enriched {len(self.discovered_tokens)} tokens with addresses"
        )

    def generate_report(self) -> str:
        """Generate a summary report."""
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("ENHANCED TOKEN DISCOVERY REPORT")
        report_lines.append(
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        report_lines.append("=" * 60)

        report_lines.append(f"\nTotal tokens discovered: {len(self.discovered_tokens)}")

        # Group by chain
        chains = {}
        for token in self.discovered_tokens:
            chain = token.get("chain", "unknown")
            if chain not in chains:
                chains[chain] = []
            chains[chain].append(token)

        report_lines.append("\nTokens by Chain:")
        for chain, tokens in chains.items():
            report_lines.append(f"  {chain}: {len(tokens)} tokens")

        # Group by DEX
        dexes = {}
        for token in self.discovered_tokens:
            dex = token.get("dex", "unknown")
            if dex not in dexes:
                dexes[dex] = []
            dexes[dex].append(token)

        report_lines.append("\nTokens by DEX:")
        for dex, tokens in sorted(dexes.items(), key=lambda x: len(x[1]), reverse=True)[
            :10
        ]:
            report_lines.append(f"  {dex}: {len(tokens)} tokens")

        # Top tokens by liquidity
        report_lines.append("\nTop Tokens by Liquidity:")
        tokens_with_liquidity = [
            t for t in self.discovered_tokens if t.get("liquidity")
        ]
        sorted_tokens = sorted(
            tokens_with_liquidity,
            key=lambda x: float(x.get("liquidity", 0)),
            reverse=True,
        )

        for i, token in enumerate(sorted_tokens[:10], 1):
            liquidity = float(token.get("liquidity", 0))
            report_lines.append(
                f"{i:2d}. {token['name']:15} | ${liquidity:12,.2f} | {token.get('dex', 'N/A')}"
            )

        return "\n".join(report_lines)

    async def run(self):
        """Run the enhanced token discovery."""
        print("Starting Enhanced Token Discovery...")
        print("=" * 60)

        try:
            # Connect to Telegram
            await self.connect()

            # Initialize database
            self.init_database()

            # Collect data from bot commands
            token_names = await self.collect_data()

            if not token_names:
                print("No token names found")
                return

            # Enrich tokens with addresses
            await self.enrich_tokens(token_names)

            # Generate report
            report = self.generate_report()

            # Print report
            print("\n" + report)

            # Save report to file
            report_path = (
                Path.home() / ".hermes" / "enhanced_token_discovery_report.txt"
            )
            with open(report_path, "w") as f:
                f.write(report)

            print(f"\nReport saved to: {report_path}")

            return report

        except Exception as e:
            print(f"Error in enhanced token discovery: {e}")
            raise
        finally:
            if self.client:
                await self.client.disconnect()
            if self.db_conn:
                self.db_conn.close()


async def main():
    """Main entry point."""
    discovery = EnhancedTokenDiscovery()
    await discovery.run()


if __name__ == "__main__":
    asyncio.run(main())
