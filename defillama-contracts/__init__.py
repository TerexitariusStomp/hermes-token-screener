#!/usr/bin/env python3
"""
DefiLlama Verified Contracts Interaction Library
A comprehensive Python library for interacting with 1,693 verified DefiLlama contracts across 49 chains.
"""

__version__ = "1.0.0"
__author__ = "Hermes Agent"

from .core.client import DefiLlamaContracts
from .core.contract import Contract
from .core.chain import Chain
from .providers.rpc import RPCProvider
from .utils.database import ContractDatabase

__all__ = [
    "DefiLlamaContracts",
    "Contract",
    "Chain",
    "RPCProvider",
    "ContractDatabase",
]