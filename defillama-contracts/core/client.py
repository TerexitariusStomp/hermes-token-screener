#!/usr/bin/env python3
"""
DefiLlama Contracts Client
Main entry point for interacting with verified contracts.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
from enum import Enum

from .contract import Contract
from .chain import Chain
from ..providers.rpc import RPCProvider
from ..utils.database import ContractDatabase


class ContractType(Enum):
    """Types of contracts in the database."""
    DEX = "dex"
    BRIDGE = "bridge"
    YIELD = "yield"
    REGISTRY = "registry"
    LENDING = "lending"
    OTHER = "other"


@dataclass
class ContractInfo:
    """Information about a verified contract."""
    chain: str
    address: str
    verification_status: str
    provider: Optional[str] = None
    code_size: Optional[int] = None
    verification_time: Optional[str] = None
    contract_type: Optional[ContractType] = None
    name: Optional[str] = None
    protocol: Optional[str] = None


class DefiLlamaContracts:
    """
    Main client for interacting with DefiLlama verified contracts.
    
    Usage:
        # Initialize client
        client = DefiLlamaContracts()
        
        # Get all deployed contracts on Ethereum
        eth_contracts = client.get_chain_contracts("Ethereum")
        
        # Get specific contract
        contract = client.get_contract("Ethereum", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984")
        
        # Interact with contract
        result = contract.call("balanceOf", "0x...")
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the DefiLlama Contracts client.
        
        Args:
            db_path: Path to the contracts database. Defaults to ~/.hermes/data/defillama_verified_contracts.db
        """
        if db_path is None:
            db_path = Path.home() / ".hermes" / "data" / "defillama_verified_contracts.db"
        
        self.db_path = db_path
        self.db = ContractDatabase(db_path)
        self.rpc_provider = RPCProvider()
        
        # Cache for loaded contracts
        self._contracts_cache: Dict[str, Contract] = {}
        self._chains_cache: Dict[str, Chain] = {}
        
        print(f"DefiLlama Contracts Client initialized")
        print(f"Database: {db_path}")
        print(f"Total contracts: {self.db.get_total_contracts()}")
        print(f"Deployed contracts: {self.db.get_deployed_contracts()}")
    
    def get_chain_contracts(
        self, 
        chain: str, 
        status: str = "deployed",
        limit: Optional[int] = None
    ) -> List[ContractInfo]:
        """
        Get all contracts on a specific chain.
        
        Args:
            chain: Chain name (e.g., "Ethereum", "Binance", "Arbitrum")
            status: Contract status filter ("deployed", "failed", "all")
            limit: Maximum number of contracts to return
            
        Returns:
            List of ContractInfo objects
        """
        contracts = self.db.get_contracts_by_chain(chain, status, limit)
        return [
            ContractInfo(
                chain=c["chain"],
                address=c["address"],
                verification_status=c["verification_status"],
                provider=c.get("provider"),
                code_size=c.get("code_size"),
                verification_time=c.get("verification_time")
            )
            for c in contracts
        ]
    
    def get_contract(self, chain: str, address: str) -> Optional[Contract]:
        """
        Get a specific contract instance.
        
        Args:
            chain: Chain name
            address: Contract address
            
        Returns:
            Contract instance or None if not found
        """
        cache_key = f"{chain}:{address}"
        
        if cache_key in self._contracts_cache:
            return self._contracts_cache[cache_key]
        
        # Check if contract exists and is deployed
        contract_info = self.db.get_contract(chain, address)
        if not contract_info or contract_info["verification_status"] != "deployed":
            return None
        
        # Create contract instance
        chain_obj = self.get_chain(chain)
        if not chain_obj:
            return None
        
        contract = Contract(
            chain=chain_obj,
            address=address,
            provider=self.rpc_provider
        )
        
        self._contracts_cache[cache_key] = contract
        return contract
    
    def get_chain(self, chain: str) -> Optional[Chain]:
        """
        Get a chain instance.
        
        Args:
            chain: Chain name
            
        Returns:
            Chain instance or None if not found
        """
        if chain in self._chains_cache:
            return self._chains_cache[chain]
        
        # Get chain config
        chain_config = self.db.get_chain_config(chain)
        if not chain_config:
            return None
        
        chain_obj = Chain(
            name=chain,
            chain_id=chain_config.get("chain_id"),
            rpc_urls=chain_config.get("rpc_urls", []),
            native_token=chain_config.get("native_token", "ETH"),
            block_time=chain_config.get("block_time", 12)
        )
        
        self._chains_cache[chain] = chain_obj
        return chain_obj
    
    def get_all_chains(self) -> List[str]:
        """
        Get all chains with deployed contracts.
        
        Returns:
            List of chain names
        """
        return self.db.get_all_chains()
    
    def get_chain_stats(self, chain: str) -> Dict[str, Any]:
        """
        Get statistics for a specific chain.
        
        Args:
            chain: Chain name
            
        Returns:
            Dictionary with chain statistics
        """
        return self.db.get_chain_stats(chain)
    
    def search_contracts(
        self,
        query: str,
        chain: Optional[str] = None,
        status: str = "deployed",
        limit: int = 50
    ) -> List[ContractInfo]:
        """
        Search contracts by name, address, or protocol.
        
        Args:
            query: Search query
            chain: Optional chain filter
            status: Contract status filter
            limit: Maximum results
            
        Returns:
            List of matching ContractInfo objects
        """
        contracts = self.db.search_contracts(query, chain, status, limit)
        return [
            ContractInfo(
                chain=c["chain"],
                address=c["address"],
                verification_status=c["verification_status"],
                provider=c.get("provider"),
                code_size=c.get("code_size"),
                verification_time=c.get("verification_time")
            )
            for c in contracts
        ]
    
    def batch_call(
        self,
        calls: List[Dict[str, Any]],
        chain: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute multiple contract calls in batch.
        
        Args:
            calls: List of call specifications
                Each call should have:
                - chain: Chain name (optional if chain parameter provided)
                - address: Contract address
                - method: Method name
                - params: Method parameters (list)
                - abi: Contract ABI (optional)
            chain: Default chain for all calls
            
        Returns:
            List of results
        """
        results = []
        
        for call_spec in calls:
            call_chain = call_spec.get("chain", chain)
            if not call_chain:
                results.append({"error": "No chain specified"})
                continue
            
            contract = self.get_contract(call_chain, call_spec["address"])
            if not contract:
                results.append({"error": f"Contract not found: {call_chain}:{call_spec['address']}"})
                continue
            
            try:
                result = contract.call(
                    method=call_spec["method"],
                    params=call_spec.get("params", []),
                    abi=call_spec.get("abi")
                )
                results.append({
                    "chain": call_chain,
                    "address": call_spec["address"],
                    "method": call_spec["method"],
                    "result": result
                })
            except Exception as e:
                results.append({
                    "chain": call_chain,
                    "address": call_spec["address"],
                    "method": call_spec["method"],
                    "error": str(e)
                })
        
        return results
    
    def get_dex_contracts(self, chain: str) -> List[ContractInfo]:
        """
        Get all DEX contracts on a chain.
        
        Args:
            chain: Chain name
            
        Returns:
            List of DEX ContractInfo objects
        """
        # This would require contract classification
        # For now, return all deployed contracts
        return self.get_chain_contracts(chain, "deployed")
    
    def get_bridge_contracts(self, chain: str) -> List[ContractInfo]:
        """
        Get all bridge contracts on a chain.
        
        Args:
            chain: Chain name
            
        Returns:
            List of bridge ContractInfo objects
        """
        # This would require contract classification
        # For now, return empty list
        return []
    
    def export_contracts(
        self,
        chain: Optional[str] = None,
        status: str = "deployed",
        format: str = "json"
    ) -> str:
        """
        Export contracts to various formats.
        
        Args:
            chain: Optional chain filter
            status: Contract status filter
            format: Export format ("json", "csv", "sql")
            
        Returns:
            Exported data as string
        """
        contracts = self.db.export_contracts(chain, status)
        
        if format == "json":
            return json.dumps(contracts, indent=2)
        elif format == "csv":
            if not contracts:
                return ""
            headers = contracts[0].keys()
            lines = [",".join(headers)]
            for c in contracts:
                line = ",".join([str(c.get(h, "")) for h in headers])
                lines.append(line)
            return "\n".join(lines)
        elif format == "sql":
            # Generate SQL insert statements
            lines = []
            for c in contracts:
                cols = ", ".join(c.keys())
                vals = ", ".join([f"'{v}'" if isinstance(v, str) else str(v) for v in c.values()])
                lines.append(f"INSERT INTO verified_contracts ({cols}) VALUES ({vals});")
            return "\n".join(lines)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def refresh_database(self):
        """
        Refresh the contracts database from source files.
        """
        print("Refreshing database...")
        self.db.refresh()
        print("Database refreshed successfully")
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the contracts database.
        
        Returns:
            Dictionary with summary statistics
        """
        return {
            "total_contracts": self.db.get_total_contracts(),
            "deployed_contracts": self.db.get_deployed_contracts(),
            "failed_contracts": self.db.get_failed_contracts(),
            "total_chains": len(self.get_all_chains()),
            "chains": self.get_all_chains()
        }
    
    def close(self):
        """Close database connections."""
        self.db.close()