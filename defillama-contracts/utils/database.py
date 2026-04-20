#!/usr/bin/env python3
"""
Database utility for accessing DefiLlama contracts.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


class ContractDatabase:
    """
    Database utility for accessing DefiLlama verified contracts.
    
    Usage:
        # Initialize database
        db = ContractDatabase()
        
        # Get all deployed contracts on Ethereum
        contracts = db.get_contracts_by_chain("Ethereum", "deployed")
        
        # Get contract info
        contract = db.get_contract("Ethereum", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984")
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database
        """
        if db_path is None:
            db_path = Path.home() / ".hermes" / "data" / "defillama_verified_contracts.db"
        
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        
        # Create tables if they don't exist
        self._create_tables()
    
    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Create verified_contracts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verified_contracts (
                chain TEXT NOT NULL,
                address TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                provider TEXT,
                code_size INTEGER,
                code_hash INTEGER,
                verification_time TEXT,
                PRIMARY KEY (chain, address)
            )
        """)
        
        # Create chain_configs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chain_configs (
                chain TEXT PRIMARY KEY,
                chain_id INTEGER,
                rpc_urls TEXT,
                native_token TEXT,
                block_time INTEGER,
                explorer_url TEXT,
                multicall_address TEXT
            )
        """)
        
        # Create improvement_pass_results table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_pass_results (
                run_id TEXT PRIMARY KEY,
                start_time TEXT,
                end_time TEXT,
                duration_seconds REAL,
                statistics TEXT,
                chain_breakdown TEXT,
                provider_breakdown TEXT
            )
        """)
        
        self.conn.commit()
    
    def get_total_contracts(self) -> int:
        """Get total number of contracts."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM verified_contracts")
        return cursor.fetchone()[0]
    
    def get_deployed_contracts(self) -> int:
        """Get number of deployed contracts."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM verified_contracts WHERE verification_status = 'deployed'")
        return cursor.fetchone()[0]
    
    def get_failed_contracts(self) -> int:
        """Get number of failed contracts."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM verified_contracts WHERE verification_status = 'failed'")
        return cursor.fetchone()[0]
    
    def get_all_chains(self) -> List[str]:
        """Get all chains with contracts."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT chain FROM verified_contracts ORDER BY chain")
        return [row[0] for row in cursor.fetchall()]
    
    def get_contracts_by_chain(
        self,
        chain: str,
        status: str = "deployed",
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get contracts by chain.
        
        Args:
            chain: Chain name
            status: Contract status filter
            limit: Maximum number of contracts
            
        Returns:
            List of contract dictionaries
        """
        cursor = self.conn.cursor()
        
        query = "SELECT * FROM verified_contracts WHERE chain = ?"
        params = [chain]
        
        if status != "all":
            query += " AND verification_status = ?"
            params.append(status)
        
        query += " ORDER BY address"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor.execute(query, params)
        
        contracts = []
        for row in cursor.fetchall():
            contracts.append({
                "chain": row["chain"],
                "address": row["address"],
                "verification_status": row["verification_status"],
                "provider": row["provider"],
                "code_size": row["code_size"],
                "code_hash": row["code_hash"],
                "verification_time": row["verification_time"]
            })
        
        return contracts
    
    def get_contract(self, chain: str, address: str) -> Optional[Dict[str, Any]]:
        """
        Get specific contract.
        
        Args:
            chain: Chain name
            address: Contract address
            
        Returns:
            Contract dictionary or None
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM verified_contracts WHERE chain = ? AND address = ?",
            (chain, address)
        )
        
        row = cursor.fetchone()
        if row:
            return {
                "chain": row["chain"],
                "address": row["address"],
                "verification_status": row["verification_status"],
                "provider": row["provider"],
                "code_size": row["code_size"],
                "code_hash": row["code_hash"],
                "verification_time": row["verification_time"]
            }
        return None
    
    def get_chain_config(self, chain: str) -> Optional[Dict[str, Any]]:
        """
        Get chain configuration.
        
        Args:
            chain: Chain name
            
        Returns:
            Chain configuration dictionary
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM chain_configs WHERE chain = ?", (chain,))
        
        row = cursor.fetchone()
        if row:
            config = {
                "chain": row["chain"],
                "chain_id": row["chain_id"],
                "native_token": row["native_token"],
                "block_time": row["block_time"],
                "explorer_url": row["explorer_url"],
                "multicall_address": row["multicall_address"]
            }
            
            # Parse RPC URLs
            if row["rpc_urls"]:
                try:
                    config["rpc_urls"] = json.loads(row["rpc_urls"])
                except:
                    config["rpc_urls"] = []
            else:
                config["rpc_urls"] = []
            
            return config
        return None
    
    def get_chain_stats(self, chain: str) -> Dict[str, Any]:
        """
        Get statistics for a chain.
        
        Args:
            chain: Chain name
            
        Returns:
            Statistics dictionary
        """
        cursor = self.conn.cursor()
        
        # Get contract counts by status
        cursor.execute("""
            SELECT verification_status, COUNT(*) as count
            FROM verified_contracts
            WHERE chain = ?
            GROUP BY verification_status
        """, (chain,))
        
        stats = {"chain": chain}
        for row in cursor.fetchall():
            stats[row["verification_status"]] = row["count"]
        
        # Get total contracts
        cursor.execute("SELECT COUNT(*) FROM verified_contracts WHERE chain = ?", (chain,))
        stats["total"] = cursor.fetchone()[0]
        
        return stats
    
    def search_contracts(
        self,
        query: str,
        chain: Optional[str] = None,
        status: str = "deployed",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search contracts.
        
        Args:
            query: Search query
            chain: Optional chain filter
            status: Contract status filter
            limit: Maximum results
            
        Returns:
            List of matching contracts
        """
        cursor = self.conn.cursor()
        
        # Build query
        sql = """
            SELECT * FROM verified_contracts
            WHERE (address LIKE ? OR chain LIKE ?)
        """
        params = [f"%{query}%", f"%{query}%"]
        
        if chain:
            sql += " AND chain = ?"
            params.append(chain)
        
        if status != "all":
            sql += " AND verification_status = ?"
            params.append(status)
        
        sql += " ORDER BY chain, address LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        
        contracts = []
        for row in cursor.fetchall():
            contracts.append({
                "chain": row["chain"],
                "address": row["address"],
                "verification_status": row["verification_status"],
                "provider": row["provider"],
                "code_size": row["code_size"],
                "code_hash": row["code_hash"],
                "verification_time": row["verification_time"]
            })
        
        return contracts
    
    def export_contracts(
        self,
        chain: Optional[str] = None,
        status: str = "deployed"
    ) -> List[Dict[str, Any]]:
        """
        Export contracts.
        
        Args:
            chain: Optional chain filter
            status: Contract status filter
            
        Returns:
            List of contracts
        """
        if chain:
            return self.get_contracts_by_chain(chain, status)
        else:
            cursor = self.conn.cursor()
            
            query = "SELECT * FROM verified_contracts"
            params = []
            
            if status != "all":
                query += " WHERE verification_status = ?"
                params.append(status)
            
            query += " ORDER BY chain, address"
            
            cursor.execute(query, params)
            
            contracts = []
            for row in cursor.fetchall():
                contracts.append({
                    "chain": row["chain"],
                    "address": row["address"],
                    "verification_status": row["verification_status"],
                    "provider": row["provider"],
                    "code_size": row["code_size"],
                    "code_hash": row["code_hash"],
                    "verification_time": row["verification_time"]
                })
            
            return contracts
    
    def add_contract(
        self,
        chain: str,
        address: str,
        verification_status: str,
        provider: Optional[str] = None,
        code_size: Optional[int] = None,
        code_hash: Optional[int] = None,
        verification_time: Optional[str] = None
    ):
        """
        Add or update contract.
        
        Args:
            chain: Chain name
            address: Contract address
            verification_status: Verification status
            provider: RPC provider used
            code_size: Contract code size
            code_hash: Contract code hash
            verification_time: Verification timestamp
        """
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO verified_contracts
            (chain, address, verification_status, provider, code_size, code_hash, verification_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            chain,
            address,
            verification_status,
            provider,
            code_size,
            code_hash,
            verification_time or datetime.now().isoformat()
        ))
        
        self.conn.commit()
    
    def add_chain_config(
        self,
        chain: str,
        chain_id: Optional[int] = None,
        rpc_urls: Optional[List[str]] = None,
        native_token: str = "ETH",
        block_time: int = 12,
        explorer_url: Optional[str] = None,
        multicall_address: Optional[str] = None
    ):
        """
        Add or update chain configuration.
        
        Args:
            chain: Chain name
            chain_id: Chain ID
            rpc_urls: List of RPC URLs
            native_token: Native token symbol
            block_time: Block time in seconds
            explorer_url: Block explorer URL
            multicall_address: Multicall contract address
        """
        cursor = self.conn.cursor()
        
        rpc_urls_json = json.dumps(rpc_urls) if rpc_urls else None
        
        cursor.execute("""
            INSERT OR REPLACE INTO chain_configs
            (chain, chain_id, rpc_urls, native_token, block_time, explorer_url, multicall_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            chain,
            chain_id,
            rpc_urls_json,
            native_token,
            block_time,
            explorer_url,
            multicall_address
        ))
        
        self.conn.commit()
    
    def delete_contract(self, chain: str, address: str):
        """
        Delete contract.
        
        Args:
            chain: Chain name
            address: Contract address
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM verified_contracts WHERE chain = ? AND address = ?",
            (chain, address)
        )
        self.conn.commit()
    
    def refresh(self):
        """Refresh database from source files."""
        # This would reload data from JSON files
        # For now, just print a message
        print("Database refresh not implemented in this version")
    
    def get_provider_stats(self) -> Dict[str, Any]:
        """
        Get statistics by provider.
        
        Returns:
            Provider statistics
        """
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT provider, 
                   COUNT(*) as total,
                   SUM(CASE WHEN verification_status = 'deployed' THEN 1 ELSE 0 END) as deployed
            FROM verified_contracts
            WHERE provider IS NOT NULL
            GROUP BY provider
            ORDER BY total DESC
        """)
        
        stats = {}
        for row in cursor.fetchall():
            stats[row["provider"]] = {
                "total": row["total"],
                "deployed": row["deployed"]
            }
        
        return stats
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()