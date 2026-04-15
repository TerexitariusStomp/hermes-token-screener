#!/usr/bin/env python3
"""
ChainGPT Bot Integration Wrapper
Uses ChainGPT bot via Telegram for token analysis and smart contract auditing.
"""

import asyncio
import sys
import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Add the scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import the Telegram client
from telethon import TelegramClient

# Configuration
SESSION_PATH = Path.home() / '.hermes' / '.telegram_session' / 'hermes_user'
TG_API_ID = int(os.getenv('TG_API_ID', '39533004'))
TG_API_HASH = os.getenv('TG_API_HASH', '958e52889177eec2fa15e9e4e4c2cc4c')

class ChainGPTBotWrapper:
    """Wrapper for using ChainGPT bot via Telegram."""
    
    def __init__(self):
        self.client = None
        self.channel = None
        
    async def connect(self):
        """Connect to Telegram and find the RickBurp channel."""
        self.client = TelegramClient(str(SESSION_PATH), TG_API_ID, TG_API_HASH)
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            raise Exception("Not authorized. Run telegram_user.py interactively first.")
        
        print("Connected to Telegram!")
        
        # Find the RickBurp channel
        async for dialog in self.client.iter_dialogs():
            if hasattr(dialog.entity, 'title') and 'rickburp' in dialog.entity.title.lower():
                self.channel = dialog.entity
                print(f"Found channel: {self.channel.title} (ID: {self.channel.id})")
                break
        
        if not self.channel:
            raise Exception("Could not find RickBurp channel")
    
    async def send_command(self, command: str, description: str = "") -> Optional[str]:
        """Send a command to ChainGPT bot and return the response."""
        try:
            print(f"  Sending command: {command} ({description})")
            
            # Get messages before sending command
            messages_before = await self.client.get_messages(self.channel, limit=1)
            last_msg_id_before = messages_before[0].id if messages_before else 0
            
            # Send command to ChainGPT bot
            await self.client.send_message(self.channel, f"{command}@ChainGPTAI_Bot")
            await asyncio.sleep(5)  # Wait for response
            
            # Get new messages after our command
            messages_after = await self.client.get_messages(self.channel, limit=10)
            
            # Find the bot's response
            bot_response = None
            me = await self.client.get_me()
            for msg in messages_after:
                if msg.id > last_msg_id_before and msg.message:
                    # Check if this is from the bot
                    if msg.sender_id and msg.sender_id != me.id:
                        # This is likely the bot's response
                        bot_response = msg.message
                        break
            
            return bot_response
            
        except Exception as e:
            print(f"Error sending command: {e}")
            return None
    
    async def analyze_token(self, token_name: str, token_address: str, chain: str = "ethereum") -> Dict:
        """Analyze a token using ChainGPT bot."""
        print(f"\nAnalyzing token: {token_name} ({token_address})")
        
        analysis = {
            'token_name': token_name,
            'token_address': token_address,
            'chain': chain,
            'timestamp': datetime.now().isoformat(),
            'analysis': {},
            'risk_assessment': {},
            'recommendations': []
        }
        
        # Ask ChainGPT to analyze the token
        questions = [
            f"What is the risk level of {token_name} token at address {token_address}?",
            f"Is the smart contract at {token_address} verified and safe?",
            f"What are the main risks of investing in {token_name}?",
            f"What is the market sentiment for {token_name} token?"
        ]
        
        for i, question in enumerate(questions, 1):
            print(f"  Question {i}: {question}")
            response = await self.send_command(f"/ai {question}", f"Question {i}")
            
            if response:
                analysis['analysis'][f'question_{i}'] = {
                    'question': question,
                    'response': response
                }
                
                # Extract risk level from response
                if 'risk' in question.lower():
                    risk_keywords = ['high', 'medium', 'low', 'safe', 'dangerous', 'scam', 'legitimate']
                    for keyword in risk_keywords:
                        if keyword in response.lower():
                            analysis['risk_assessment'][keyword] = response
                            break
            
            # Small delay between questions
            await asyncio.sleep(2)
        
        # Generate recommendations based on analysis
        if analysis['analysis']:
            analysis['recommendations'] = [
                "Review the smart contract audit results",
                "Check token liquidity and trading volume",
                "Verify token social media presence",
                "Monitor price action and market sentiment"
            ]
        
        return analysis
    
    async def audit_contract(self, contract_address: str, chain: str = "ethereum") -> Dict:
        """Audit a smart contract using ChainGPT bot."""
        print(f"\nAuditing contract: {contract_address} on {chain}")
        
        audit = {
            'contract_address': contract_address,
            'chain': chain,
            'timestamp': datetime.now().isoformat(),
            'audit_results': {},
            'security_score': 0,
            'vulnerabilities': [],
            'recommendations': []
        }
        
        # Send audit command
        response = await self.send_command(f"/audit {contract_address}", "Smart contract audit")
        
        if response:
            audit['audit_results']['response'] = response
            
            # Extract security information
            security_keywords = ['safe', 'vulnerable', 'risk', 'secure', 'danger', 'warning']
            for keyword in security_keywords:
                if keyword in response.lower():
                    audit['vulnerabilities'].append({
                        'keyword': keyword,
                        'context': response[:200]
                    })
            
            # Calculate security score (simple heuristic)
            if 'safe' in response.lower() or 'secure' in response.lower():
                audit['security_score'] = 80
            elif 'warning' in response.lower() or 'risk' in response.lower():
                audit['security_score'] = 50
            elif 'danger' in response.lower() or 'vulnerable' in response.lower():
                audit['security_score'] = 20
            else:
                audit['security_score'] = 60
            
            # Generate recommendations
            audit['recommendations'] = [
                "Review the audit report carefully",
                "Check for known vulnerabilities",
                "Verify contract ownership and permissions",
                "Monitor contract for unusual activity"
            ]
        
        return audit
    
    async def get_market_sentiment(self, token_name: str) -> Dict:
        """Get market sentiment for a token using ChainGPT bot."""
        print(f"\nGetting market sentiment for: {token_name}")
        
        sentiment = {
            'token_name': token_name,
            'timestamp': datetime.now().isoformat(),
            'sentiment_analysis': {},
            'market_trends': [],
            'recommendations': []
        }
        
        # Ask about market sentiment
        questions = [
            f"What is the current market sentiment for {token_name}?",
            f"Is {token_name} a good investment right now?",
            f"What are the short-term and long-term prospects for {token_name}?"
        ]
        
        for i, question in enumerate(questions, 1):
            response = await self.send_command(f"/ai {question}", f"Sentiment question {i}")
            
            if response:
                sentiment['sentiment_analysis'][f'question_{i}'] = {
                    'question': question,
                    'response': response
                }
                
                # Extract sentiment keywords
                sentiment_keywords = ['bullish', 'bearish', 'neutral', 'positive', 'negative', 'optimistic', 'pessimistic']
                for keyword in sentiment_keywords:
                    if keyword in response.lower():
                        sentiment['market_trends'].append(keyword)
            
            await asyncio.sleep(2)
        
        # Generate recommendations
        if sentiment['sentiment_analysis']:
            sentiment['recommendations'] = [
                "Monitor market trends and news",
                "Check trading volume and liquidity",
                "Set stop-loss and take-profit levels",
                "Diversify your portfolio"
            ]
        
        return sentiment
    
    async def enrich_token_with_chaingpt(self, token: Dict) -> Dict:
        """Enrich a token with ChainGPT analysis."""
        print(f"\n=== Enriching token with ChainGPT: {token.get('name', 'Unknown')} ===")
        
        enriched_token = token.copy()
        
        # Get token analysis
        if token.get('address'):
            analysis = await self.analyze_token(
                token.get('name', 'Unknown'),
                token['address'],
                token.get('chain', 'ethereum')
            )
            enriched_token['chaingpt_analysis'] = analysis
        
        # Get contract audit if we have an address
        if token.get('address'):
            audit = await self.audit_contract(
                token['address'],
                token.get('chain', 'ethereum')
            )
            enriched_token['chaingpt_audit'] = audit
        
        # Get market sentiment
        if token.get('name'):
            sentiment = await self.get_market_sentiment(token['name'])
            enriched_token['chaingpt_sentiment'] = sentiment
        
        return enriched_token
    
    async def disconnect(self):
        """Disconnect from Telegram."""
        if self.client:
            await self.client.disconnect()

async def main():
    """Main entry point for testing."""
    wrapper = ChainGPTBotWrapper()
    
    try:
        await wrapper.connect()
        
        # Test with a sample token
        test_token = {
            'name': 'WETH',
            'address': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
            'chain': 'ethereum'
        }
        
        # Enrich the token
        enriched = await wrapper.enrich_token_with_chaingpt(test_token)
        
        # Print results
        print("\n=== Enrichment Results ===")
        print(f"Token: {enriched['name']}")
        print(f"Address: {enriched['address']}")
        
        if 'chaingpt_analysis' in enriched:
            print(f"\nAnalysis: {len(enriched['chaingpt_analysis']['analysis'])} questions answered")
        
        if 'chaingpt_audit' in enriched:
            print(f"Audit: Security score {enriched['chaingpt_audit']['security_score']}/100")
        
        if 'chaingpt_sentiment' in enriched:
            print(f"Sentiment: {len(enriched['chaingpt_sentiment']['sentiment_analysis'])} questions answered")
        
    finally:
        await wrapper.disconnect()

if __name__ == "__main__":
    asyncio.run(main())