#!/usr/bin/env python3
"""
DefiLlama Verified Contracts Interaction Library
A comprehensive Python library for interacting with 1,693 verified DefiLlama contracts across 49 chains.

Database Location: ~/.hermes/data/defillama_verified_contracts.db
- Contains 1,693 contracts (1,308 deployed, 77.3% success rate)
- Covers 49 chains including Ethereum, Base, Arbitrum, Polygon, etc.
- Verified via on-chain bytecode checks using dRPC providers

Key Features:
1. Universal Contract Classifier - Probes contracts on-chain to detect type/methods
2. Smart Contract Wrapper - Auto-detects protocol and provides typed methods
3. Price Fetcher - Fetches prices from DEX contracts
4. Interaction Guide - Complete documentation for any contract

Usage:
    from defillama_contracts import DefiLlamaContracts, PriceFetcher
    
    # Initialize client
    client = DefiLlamaContracts()
    
    # Get contracts on a chain
    contracts = client.get_chain_contracts("Ethereum", "deployed")
    
    # Classify any contract
    classification = client.classify_contract("Ethereum", "0x...")
    
    # Get smart contract wrapper
    smart = client.get_smart_contract("Ethereum", "0x...")
    
    # Fetch DEX prices
    fetcher = PriceFetcher(client)
    prices = fetcher.fetch_all_prices("Base", token_a, token_b)
    
    # Access database directly
    import sqlite3
    db_path = "~/.hermes/data/defillama_verified_contracts.db"
    conn = sqlite3.connect(db_path)
    
    # Query deployed contracts
    cursor = conn.execute(
        "SELECT chain, address FROM verified_contracts WHERE verification_status = 'deployed'"
    )
"""

__version__ = "1.0.0"
__author__ = "Hermes Agent"

from .core.client import DefiLlamaContracts
from .core.contract import Contract
from .core.chain import Chain
from .core.price_fetcher import PriceFetcher
from .providers.rpc import RPCProvider
from .utils.database import ContractDatabase
from .protocols import (
    ProtocolType,
    ContractRole,
    ProtocolContract,
    ContractClassifier,
    catalog,
    registry,
)

__all__ = [
    "DefiLlamaContracts",
    "Contract",
    "Chain",
    "PriceFetcher",
    "RPCProvider",
    "ContractDatabase",
    "ProtocolType",
    "ContractRole",
    "ProtocolContract",
    "ContractClassifier",
    "catalog",
    "registry",
]
