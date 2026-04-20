#!/usr/bin/env python3
"""
Price Fetcher for DEX contracts.
Fetches prices from DEX contracts on any chain.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from decimal import Decimal

try:
    from web3 import Web3
    from web3.exceptions import ContractLogicError
except ImportError:
    Web3 = None
    ContractLogicError = Exception


# DEX contract ABIs
ROUTER_ABI = [
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"},
        ],
        "name": "getAmountsOut",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "WETH",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "factory",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

FACTORY_ABI = [
    {
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
        ],
        "name": "getPair",
        "outputs": [{"name": "pair", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

PAIR_ABI = [
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Chain RPC endpoints
CHAIN_RPCS = {
    "Base": [
        "https://base.llamarpc.com",
        "https://base.drpc.org",
        "https://base-mainnet.public.blastapi.io",
        "https://mainnet.base.org",
    ],
    "Ethereum": [
        "https://eth.llamarpc.com",
        "https://eth.drpc.org",
        "https://ethereum.publicnode.com",
        "https://rpc.ankr.com/eth",
    ],
    "Arbitrum": [
        "https://arb1.arbitrum.io/rpc",
        "https://arbitrum.llamarpc.com",
    ],
    "Optimism": [
        "https://mainnet.optimism.io",
        "https://optimism.llamarpc.com",
    ],
    "Polygon": [
        "https://polygon-rpc.com",
        "https://polygon.llamarpc.com",
    ],
}


class PriceFetcher:
    """Fetches prices from DEX contracts."""

    def __init__(self, client=None):
        """
        Initialize price fetcher.

        Args:
            client: DefiLlamaContracts instance (optional)
        """
        self.client = client
        self._w3_cache = {}

    def get_web3(self, chain: str) -> Optional[Web3]:
        """Get Web3 instance for a chain."""
        if Web3 is None:
            print("Error: web3 not installed. Run: pip install web3")
            return None

        if chain in self._w3_cache:
            w3 = self._w3_cache[chain]
            if w3.is_connected():
                return w3

        rpcs = CHAIN_RPCS.get(chain, [])
        for rpc in rpcs:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc))
                if w3.is_connected():
                    self._w3_cache[chain] = w3
                    return w3
            except Exception:
                continue

        return None

    def get_token_info(self, w3: Web3, token_address: str) -> Dict[str, Any]:
        """Get token symbol and decimals."""
        try:
            contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
            symbol = contract.functions.symbol().call()
            decimals = contract.functions.decimals().call()
            return {"symbol": symbol, "decimals": decimals}
        except:
            return {"symbol": token_address[:10] + "...", "decimals": 18}

    def fetch_price(
        self,
        chain: str,
        dex_address: str,
        token_a: str,
        token_b: str,
        amount: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Fetch price from a specific DEX.

        Args:
            chain: Chain name
            dex_address: DEX router address
            token_a: Token A address
            token_b: Token B address
            amount: Amount of token A to price

        Returns:
            Dictionary with price information
        """
        w3 = self.get_web3(chain)
        if not w3:
            return {"error": f"Could not connect to {chain} RPC"}

        # Get token info
        token_a_info = self.get_token_info(w3, token_a)
        token_b_info = self.get_token_info(w3, token_b)

        try:
            # Create contract instance
            router = w3.eth.contract(address=dex_address, abi=ROUTER_ABI)

            # Calculate amount in
            amount_in = int(amount * (10 ** token_a_info["decimals"]))
            path = [token_a, token_b]

            # Get price
            amounts_out = router.functions.getAmountsOut(amount_in, path).call()
            amount_out = amounts_out[-1]

            # Calculate human-readable amount
            amount_out_human = Decimal(amount_out) / Decimal(
                10 ** token_b_info["decimals"]
            )

            # Try to get pool address
            pool_address = None
            try:
                factory_address = router.functions.factory().call()
                factory = w3.eth.contract(address=factory_address, abi=FACTORY_ABI)
                pool_address = factory.functions.getPair(token_a, token_b).call()
                if pool_address == "0x0000000000000000000000000000000000000000":
                    pool_address = None
            except:
                pass

            # Try to get protocol name
            protocol = "DEX"
            if self.client:
                try:
                    classification = self.client.classify_contract(chain, dex_address)
                    if classification.get("suggested_protocol_type"):
                        protocol = classification["suggested_protocol_type"].upper()
                except:
                    pass

            return {
                "chain": chain,
                "dex_address": dex_address,
                "protocol": protocol,
                "token_a": token_a,
                "token_b": token_b,
                "token_a_symbol": token_a_info["symbol"],
                "token_b_symbol": token_b_info["symbol"],
                "amount_in": amount,
                "amount_out": str(amount_out_human),
                "amount_out_raw": str(amount_out),
                "token_a_decimals": token_a_info["decimals"],
                "token_b_decimals": token_b_info["decimals"],
                "pool_address": pool_address,
            }

        except Exception as e:
            return {
                "chain": chain,
                "dex_address": dex_address,
                "token_a": token_a,
                "token_b": token_b,
                "error": str(e),
            }

    def fetch_all_prices(
        self, chain: str, token_a: str, token_b: str, amount: float = 1.0
    ) -> List[Dict[str, Any]]:
        """
        Fetch prices from all DEXes on a chain.

        Args:
            chain: Chain name
            token_a: Token A address
            token_b: Token B address
            amount: Amount of token A to price

        Returns:
            List of price results from each DEX
        """
        if not self.client:
            return [{"error": "Client not initialized"}]

        # Get deployed contracts
        contracts = self.client.get_chain_contracts(chain, "deployed")

        results = []
        checked = 0

        for contract in contracts:
            if checked >= 20:  # Limit to 20 contracts to avoid rate limiting
                break

            try:
                # Quick classification to check if it's a DEX
                classification = self.client.classify_contract(chain, contract.address)

                if classification.get("suggested_protocol_type") == "dex":
                    # Fetch price
                    result = self.fetch_price(
                        chain=chain,
                        dex_address=contract.address,
                        token_a=token_a,
                        token_b=token_b,
                        amount=amount,
                    )

                    if "error" not in result:
                        results.append(result)
                    else:
                        # Only include errors for debugging
                        pass

                    checked += 1
                    time.sleep(0.5)  # Rate limiting

            except Exception:
                continue

        return results


# Convenience functions
def fetch_dex_price(
    chain: str, dex_address: str, token_a: str, token_b: str, amount: float = 1.0
) -> Dict[str, Any]:
    """Fetch price from a specific DEX."""
    fetcher = PriceFetcher()
    return fetcher.fetch_price(chain, dex_address, token_a, token_b, amount)


def fetch_all_dex_prices(
    chain: str, token_a: str, token_b: str, amount: float = 1.0
) -> List[Dict[str, Any]]:
    """Fetch prices from all DEXes on a chain."""
    from defillama_contracts import DefiLlamaContracts

    client = DefiLlamaContracts()
    fetcher = PriceFetcher(client)
    results = fetcher.fetch_all_prices(chain, token_a, token_b, amount)
    client.close()
    return results
