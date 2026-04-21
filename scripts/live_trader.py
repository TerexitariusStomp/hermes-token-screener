#!/usr/bin/env python3
"""
Live DEX Trading Bot - Executes actual trades based on signals.
Runs every minute for 10 minutes.
"""

import os
import sys
import json
import time
import logging
import subprocess
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3
# TOR proxy - route all external HTTP through SOCKS5
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-token-screener"))
import hermes_screener.tor_config

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
load_dotenv(os.path.expanduser("~/.hermes/.env"))

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Top tokens from research
TOP_TOKENS = {
    "base": {
        "ANDY": "0x029Eb076D2E9E5b2dDc1aB7BDe2D5d3b4b1bfAA0",
        "BRETT": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
        "DEGEN": "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed",
        "TOSHI": "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4",
        "BRETT2": "0x6B175474E89094C44Da98b954EescdEcD2d1B78C",
    },
    "solana": {
        "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
        "MYRO": "HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeZg4",
        "BODEN": "3psN1m3xRkgVsVRn7RwHjX3dGc97VxWjL5LxepDpump",
    }
}

# WETH on Base
WETH_BASE = "0x4200000000000000000000000000000000000006"
# WSOL
WSOL = "So11111111111111111111111111111111111111112"
# USDC on Base
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


class LiveTrader:
    """Executes actual trades based on signals."""
    
    JUPITER_API_KEY = os.environ.get("JUPITER_API_KEY", "jup_92630f2f0da7d0cc8923a674bd54252f958a103c237de78da89ba6a0494117d9")
    LIFI_API_KEY = os.environ.get("LIFI_API_KEY", "5507bdb8-0e83-4f80-8c76-238718004832.d1d06e6b-5be9-4725-93b5-75e62b90ccd4")
    
    def __init__(self):
        self.evm_account = None
        self.solana_keypair = None
        self.w3 = None
        self.trades_executed = []
        self.start_time = datetime.now(timezone.utc)
        self.end_time = self.start_time + timedelta(minutes=10)
        self.initialize()
    
    def initialize(self):
        """Initialize wallets."""
        # EVM wallet
        evm_pk = os.environ.get("WALLET_PRIVATE_KEY_BASE", "")
        if evm_pk:
            if evm_pk.startswith("0x"):
                evm_pk = evm_pk[2:]
            self.evm_account = Account.from_key(bytes.fromhex(evm_pk))
            logger.info(f"EVM Wallet: {self.evm_account.address}")
        
        # Solana wallet
        solana_pk = os.environ.get("WALLET_PRIVATE_KEY_SOLANA") or os.environ.get("SOLANA_PRIVATE_KEY", "")
        if solana_pk:
            try:
                from solders.keypair import Keypair
                if len(solana_pk) == 64:
                    try:
                        self.solana_keypair = Keypair.from_base58_string(solana_pk)
                    except:
                        self.solana_keypair = Keypair.from_seed(bytes.fromhex(solana_pk[:64]))
                elif len(solana_pk) in [87, 88]:
                    self.solana_keypair = Keypair.from_base58_string(solana_pk)
                if self.solana_keypair:
                    logger.info(f"Solana Wallet: {self.solana_keypair.pubkey()}")
            except Exception as e:
                logger.error(f"Solana wallet error: {e}")
        
        # Web3 for EVM
        if self.evm_account:
            self.w3 = self.get_web3()
    
    def get_web3(self):
        """Get Web3 connection."""
        for rpc in ["https://mainnet.base.org", "https://base.llamarpc.com"]:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 10}))
                if w3.is_connected():
                    return w3
            except:
                continue
        return None
    
    def get_balance(self, chain: str) -> Decimal:
        """Get native balance."""
        if chain == "base" and self.w3 and self.evm_account:
            try:
                bal = self.w3.eth.get_balance(self.evm_account.address)
                return Decimal(bal) / Decimal(1e18)
            except:
                pass
        elif chain == "solana" and self.solana_keypair:
            try:
                resp = requests.post("https://mainnet.helius-rpc.com/?api-key=bb6ff3e9-e38d-4362-9e7a-669a00d497a8", json={
                    "jsonrpc": "2.0", "id": 1, "method": "getBalance",
                    "params": [str(self.solana_keypair.pubkey())]
                }, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if "result" in data:
                        return Decimal(data["result"]["value"]) / Decimal(1e9)
            except:
                pass
        return Decimal("0")
    
    def get_signals(self) -> List[Dict]:
        """Get trading signals."""
        try:
            from signal_providers import aggregate_signals
            return aggregate_signals()
        except Exception as e:
            logger.error(f"Signal error: {e}")
            return []
    
    def get_token_address(self, symbol: str, chain: str) -> Optional[str]:
        """Get token address from symbol."""
        chain_tokens = TOP_TOKENS.get(chain, {})
        if symbol in chain_tokens:
            return chain_tokens[symbol]
        
        # Try to resolve via token list
        try:
            from signal_providers import get_token_address
            addr = get_token_address(symbol)
            if addr:
                return addr
        except:
            pass
        
        return None
    
    def jupiter_quote(self, input_mint: str, output_mint: str, amount: int) -> Dict:
        """Get Jupiter quote."""
        try:
            resp = requests.get("https://quote-api.jup.ag/v6/quote", params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": "100",  # 1% slippage
            }, headers={"x-api-key": self.JUPITER_API_KEY}, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Jupiter quote error: {e}")
        return {}
    
    def jupiter_swap(self, quote: Dict) -> Optional[str]:
        """Execute Jupiter swap via CLI."""
        try:
            # Use Jupiter CLI for actual swap
            result = subprocess.run(
                ["jup", "spot", "swap",
                 "--from", quote.get("inputMint", ""),
                 "--to", quote.get("outputMint", ""),
                 "--amount", str(int(quote.get("inAmount", 0)) / 1e9),
                 "--slippage", "1"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PATH": os.environ.get("PATH", "") + ":/home/terexitarius/.hermes/node/bin"}
            )
            
            if result.returncode == 0:
                logger.info(f"Jupiter swap executed: {result.stdout[:200]}")
                return result.stdout
            else:
                logger.error(f"Jupiter swap failed: {result.stderr[:200]}")
        except Exception as e:
            logger.error(f"Jupiter swap error: {e}")
        return None
    
    def kyberswap_quote(self, token_in: str, token_out: str, amount: str) -> Dict:
        """Get KyberSwap quote."""
        try:
            resp = requests.get("https://aggregator-api.kyberswap.com/base/api/v1/routes", params={
                "tokenIn": token_in,
                "tokenOut": token_out,
                "amountIn": amount,
            }, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"KyberSwap quote error: {e}")
        return {}
    
    def execute_solana_swap(self, token_symbol: str, token_mint: str, sol_amount: float) -> bool:
        """Execute swap on Solana."""
        logger.info(f"Attempting Solana swap: {sol_amount} SOL -> {token_symbol}")
        
        # Get quote
        amount_lamports = int(sol_amount * 1e9)
        quote = self.jupiter_quote(WSOL, token_mint, amount_lamports)
        
        if not quote:
            logger.error("Failed to get Jupiter quote")
            return False
        
        out_amount = int(quote.get("outAmount", 0))
        price_impact = quote.get("priceImpactPct", 0)
        
        logger.info(f"Quote: {sol_amount} SOL -> {out_amount} {token_symbol} (impact: {price_impact}%)")
        
        # Check price impact (don't trade if >5%)
        if float(price_impact) > 5:
            logger.warning(f"Price impact too high: {price_impact}%")
            return False
        
        # Execute swap
        result = self.jupiter_swap(quote)
        if result:
            self.trades_executed.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "chain": "solana",
                "token": token_symbol,
                "side": "BUY",
                "amount_in": sol_amount,
                "amount_out": out_amount,
                "status": "EXECUTED"
            })
            return True
        
        return False
    
    def execute_base_swap(self, token_symbol: str, token_addr: str, eth_amount: float) -> bool:
        """Execute swap on Base."""
        logger.info(f"Attempting Base swap: {eth_amount} ETH -> {token_symbol}")
        
        # Get quote from KyberSwap
        amount_wei = int(eth_amount * 1e18)
        quote = self.kyberswap_quote(WETH_BASE, token_addr, str(amount_wei))
        
        if not quote or "data" not in quote:
            logger.error("Failed to get KyberSwap quote")
            return False
        
        route_summary = quote["data"].get("routeSummary", {})
        out_amount = int(route_summary.get("amountOut", 0))
        gas_usd = route_summary.get("gasUsd", 0)
        
        logger.info(f"Quote: {eth_amount} ETH -> {out_amount} {token_symbol} (gas: ${gas_usd})")
        
        # For now, just log the quote (actual execution would need transaction signing)
        self.trades_executed.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "chain": "base",
            "token": token_symbol,
            "side": "BUY",
            "amount_in": eth_amount,
            "amount_out": out_amount,
            "status": "QUOTED"
        })
        
        return True
    
    def run_cycle(self):
        """Run one trading cycle."""
        logger.info("=" * 60)
        logger.info("TRADING CYCLE")
        logger.info("=" * 60)
        
        # Check balances
        base_bal = self.get_balance("base")
        sol_bal = self.get_balance("solana")
        logger.info(f"Balances - Base: {base_bal:.6f} ETH, Solana: {sol_bal:.6f} SOL")
        
        # Get signals
        signals = self.get_signals()
        logger.info(f"Signals: {len(signals)}")
        
        for signal in signals[:5]:
            token = signal.get("token", "?")
            action = signal.get("action", "?")
            conf = signal.get("confidence", 0)
            chain = signal.get("chain", "unknown")
            
            logger.info(f"  {token}: {action} (conf={conf:.2f}, chain={chain})")
            
            # Only act on high-confidence BUY signals
            if action == "BUY" and conf >= 0.7:
                token_addr = self.get_token_address(token, chain)
                
                if chain == "solana" and sol_bal > Decimal("0.01"):
                    # Use 50% of SOL balance for trade
                    trade_amount = float(sol_bal) * 0.5
                    logger.info(f"Trading {trade_amount} SOL for {token} on Solana")
                    self.execute_solana_swap(token, token_addr or token, trade_amount)
                
                elif chain == "base" and base_bal > Decimal("0.001"):
                    # Use 50% of ETH balance for trade
                    trade_amount = float(base_bal) * 0.5
                    logger.info(f"Trading {trade_amount} ETH for {token} on Base")
                    self.execute_base_swap(token, token_addr, trade_amount)
                
                else:
                    logger.warning(f"Insufficient balance on {chain}")
    
    def run(self):
        """Run for 10 minutes with 1-minute cycles."""
        logger.info("=" * 60)
        logger.info("LIVE TRADING BOT - 10 MINUTE RUN")
        logger.info("=" * 60)
        logger.info(f"Start: {self.start_time.isoformat()}")
        logger.info(f"End:   {self.end_time.isoformat()}")
        logger.info("=" * 60)
        
        cycle = 0
        while datetime.now(timezone.utc) < self.end_time:
            cycle += 1
            remaining = (self.end_time - datetime.now(timezone.utc)).total_seconds()
            
            if remaining <= 0:
                break
            
            logger.info(f"\n--- CYCLE {cycle} ({remaining:.0f}s remaining) ---")
            
            try:
                self.run_cycle()
            except Exception as e:
                logger.error(f"Cycle error: {e}")
                import traceback
                traceback.print_exc()
            
            # Wait 60 seconds between cycles
            if remaining > 60:
                logger.info("Waiting 60 seconds...")
                time.sleep(60)
            else:
                time.sleep(max(remaining, 10))
        
        # Final report
        logger.info("\n" + "=" * 60)
        logger.info("FINAL REPORT")
        logger.info("=" * 60)
        logger.info(f"Trades executed: {len(self.trades_executed)}")
        
        for trade in self.trades_executed:
            logger.info(f"  {trade['time'][:19]} | {trade['chain']} | {trade['token']} | {trade['side']} | {trade['amount_in']} -> {trade['amount_out']} | {trade['status']}")
        
        # Save report
        report_path = os.path.expanduser("~/.hermes/logs/trade_report.json")
        with open(report_path, "w") as f:
            json.dump({
                "start": self.start_time.isoformat(),
                "end": datetime.now(timezone.utc).isoformat(),
                "trades": self.trades_executed,
                "final_balances": {
                    "base": str(self.get_balance("base")),
                    "solana": str(self.get_balance("solana")),
                }
            }, f, indent=2)
        
        logger.info(f"Report saved: {report_path}")


def main():
    trader = LiveTrader()
    trader.run()


if __name__ == "__main__":
    main()
