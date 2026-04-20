#!/usr/bin/env python3
"""
RPC Provider for blockchain interactions.
"""

import json
import time
import hashlib
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum
import urllib.request
import urllib.error
import ssl


class RPCMethod(Enum):
    """JSON-RPC methods."""
    ETH_GET_BALANCE = "eth_getBalance"
    ETH_GET_CODE = "eth_getCode"
    ETH_GET_STORAGE_AT = "eth_getStorageAt"
    ETH_CALL = "eth_call"
    ETH_ESTIMATE_GAS = "eth_estimateGas"
    ETH_GAS_PRICE = "eth_gasPrice"
    ETH_SEND_RAW_TRANSACTION = "eth_sendRawTransaction"
    ETH_GET_TRANSACTION_RECEIPT = "eth_getTransactionReceipt"
    ETH_GET_BLOCK_BY_NUMBER = "eth_getBlockByNumber"
    ETH_GET_LOGS = "eth_getLogs"
    ETH_BLOCK_NUMBER = "eth_blockNumber"
    ETH_GET_TRANSACTION_COUNT = "eth_getTransactionCount"


@dataclass
class RPCResponse:
    """JSON-RPC response."""
    jsonrpc: str
    id: int
    result: Any = None
    error: Optional[Dict] = None


class RPCProvider:
    """
    RPC provider for blockchain interactions with multi-provider fallback.
    
    Usage:
        # Initialize provider
        provider = RPCProvider()
        
        # Get balance
        balance = provider.get_balance("Ethereum", "0x...")
        
        # Call contract
        result = provider.call_contract("Ethereum", "0x...", "0x...")
    """
    
    def __init__(self, timeout: int = 10, max_retries: int = 3):
        """
        Initialize RPC provider.
        
        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Chain RPC URLs (populated from Chain class)
        self.chain_rpcs: Dict[str, List[str]] = {}
        
        # Request ID counter
        self._request_id = 0
        
        # Rate limiting
        self._last_request_time: Dict[str, float] = {}
        self._min_request_interval = 0.1  # seconds
    
    def set_chain_rpcs(self, chain: str, rpc_urls: List[str]):
        """
        Set RPC URLs for a chain.
        
        Args:
            chain: Chain name
            rpc_urls: List of RPC URLs
        """
        self.chain_rpcs[chain] = rpc_urls
    
    def _get_next_id(self) -> int:
        """Get next JSON-RPC request ID."""
        self._request_id += 1
        return self._request_id
    
    def _make_request(
        self,
        chain: str,
        method: str,
        params: List[Any],
        rpc_url: Optional[str] = None
    ) -> RPCResponse:
        """
        Make JSON-RPC request.
        
        Args:
            chain: Chain name
            method: JSON-RPC method
            params: Method parameters
            rpc_url: Specific RPC URL to use
            
        Returns:
            RPCResponse object
        """
        # Rate limiting
        current_time = time.time()
        if chain in self._last_request_time:
            elapsed = current_time - self._last_request_time[chain]
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)
        
        self._last_request_time[chain] = time.time()
        
        # Get RPC URLs
        if rpc_url:
            rpc_urls = [rpc_url]
        elif chain in self.chain_rpcs:
            rpc_urls = self.chain_rpcs[chain]
        else:
            raise ValueError(f"No RPC URLs configured for chain: {chain}")
        
        # Try each RPC URL
        last_error = None
        for attempt, url in enumerate(rpc_urls):
            try:
                # Prepare request
                request_id = self._get_next_id()
                payload = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params
                }
                
                # Make request
                ctx = ssl.create_default_context()
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                
                with urllib.request.urlopen(req, context=ctx, timeout=self.timeout) as resp:
                    response_data = json.loads(resp.read().decode())
                    
                    # Parse response
                    response = RPCResponse(
                        jsonrpc=response_data.get("jsonrpc", "2.0"),
                        id=response_data.get("id", request_id),
                        result=response_data.get("result"),
                        error=response_data.get("error")
                    )
                    
                    if response.error:
                        raise RuntimeError(f"RPC error: {response.error}")
                    
                    return response
                    
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}: {e.reason}"
                if e.code == 429:  # Rate limited
                    time.sleep(1)
                continue
            except Exception as e:
                last_error = str(e)
                continue
        
        raise RuntimeError(f"All RPC URLs failed for {chain}. Last error: {last_error}")
    
    def get_balance(self, chain: str, address: str, block: str = "latest") -> int:
        """
        Get native token balance.
        
        Args:
            chain: Chain name
            address: Address to check
            block: Block number or "latest"
            
        Returns:
            Balance in wei
        """
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_GET_BALANCE.value,
            params=[address, block]
        )
        
        if response.result:
            return int(response.result, 16)
        return 0
    
    def get_code(self, chain: str, address: str, block: str = "latest") -> str:
        """
        Get contract bytecode.
        
        Args:
            chain: Chain name
            address: Contract address
            block: Block number or "latest"
            
        Returns:
            Bytecode as hex string
        """
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_GET_CODE.value,
            params=[address, block]
        )
        
        return response.result or "0x"
    
    def get_storage_at(
        self,
        chain: str,
        address: str,
        position: Union[int, str],
        block: str = "latest"
    ) -> str:
        """
        Get storage value at position.
        
        Args:
            chain: Chain name
            address: Contract address
            position: Storage position
            block: Block number or "latest"
            
        Returns:
            Storage value as hex string
        """
        if isinstance(position, int):
            position = hex(position)
        
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_GET_STORAGE_AT.value,
            params=[address, position, block]
        )
        
        return response.result or "0x"
    
    def call_contract(
        self,
        chain: str,
        to: str,
        data: str,
        block: str = "latest",
        from_address: Optional[str] = None,
        value: int = 0
    ) -> str:
        """
        Call contract method (read-only).
        
        Args:
            chain: Chain name
            to: Contract address
            data: Encoded method call
            block: Block number or "latest"
            from_address: From address (optional)
            value: ETH value to send
            
        Returns:
            Encoded result
        """
        params = {
            "to": to,
            "data": data,
            "value": hex(value)
        }
        
        if from_address:
            params["from"] = from_address
        
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_CALL.value,
            params=[params, block]
        )
        
        return response.result or "0x"
    
    def estimate_gas(
        self,
        chain: str,
        to: str,
        data: str,
        from_address: Optional[str] = None,
        value: int = 0
    ) -> int:
        """
        Estimate gas for transaction.
        
        Args:
            chain: Chain name
            to: Contract address
            data: Transaction data
            from_address: From address (optional)
            value: ETH value to send
            
        Returns:
            Estimated gas
        """
        params = {
            "to": to,
            "data": data,
            "value": hex(value)
        }
        
        if from_address:
            params["from"] = from_address
        
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_ESTIMATE_GAS.value,
            params=[params]
        )
        
        if response.result:
            return int(response.result, 16)
        return 21000  # Default gas limit
    
    def get_gas_price(self, chain: str) -> int:
        """
        Get current gas price.
        
        Args:
            chain: Chain name
            
        Returns:
            Gas price in wei
        """
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_GAS_PRICE.value,
            params=[]
        )
        
        if response.result:
            return int(response.result, 16)
        return 0
    
    def send_transaction(
        self,
        chain: str,
        to: str,
        data: str,
        private_key: str,
        gas_limit: Optional[int] = None,
        gas_price: Optional[int] = None,
        value: int = 0,
        nonce: Optional[int] = None
    ) -> str:
        """
        Send transaction.
        
        Args:
            chain: Chain name
            to: Contract address
            data: Transaction data
            private_key: Private key for signing
            gas_limit: Gas limit
            gas_price: Gas price
            value: ETH value to send
            nonce: Transaction nonce
            
        Returns:
            Transaction hash
        """
        # This is a simplified implementation
        # In production, you'd use a proper transaction signing library
        
        # Get nonce if not provided
        if nonce is None:
            # You'd need to implement get_transaction_count
            nonce = 0
        
        # Get gas price if not provided
        if gas_price is None:
            gas_price = self.get_gas_price(chain)
        
        # Estimate gas if not provided
        if gas_limit is None:
            gas_limit = self.estimate_gas(chain, to, data, value=value)
        
        # Create transaction
        transaction = {
            "to": to,
            "data": data,
            "value": hex(value),
            "gas": hex(gas_limit),
            "gasPrice": hex(gas_price),
            "nonce": hex(nonce),
            "chainId": self._get_chain_id(chain)
        }
        
        # Sign and send transaction
        # This would require a proper signing library
        raise NotImplementedError("Transaction signing not implemented in this example")
    
    def get_logs(
        self,
        chain: str,
        address: str,
        topics: List[str],
        from_block: Union[int, str] = "latest",
        to_block: Union[int, str] = "latest"
    ) -> List[Dict]:
        """
        Get event logs.
        
        Args:
            chain: Chain name
            address: Contract address
            topics: Filter topics
            from_block: Start block
            to_block: End block
            
        Returns:
            List of log entries
        """
        params = {
            "address": address,
            "topics": topics,
            "fromBlock": from_block if isinstance(from_block, str) else hex(from_block),
            "toBlock": to_block if isinstance(to_block, str) else hex(to_block)
        }
        
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_GET_LOGS.value,
            params=[params]
        )
        
        return response.result or []
    
    def get_block_number(self, chain: str) -> int:
        """
        Get current block number.
        
        Args:
            chain: Chain name
            
        Returns:
            Current block number
        """
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_BLOCK_NUMBER.value,
            params=[]
        )
        
        if response.result:
            return int(response.result, 16)
        return 0
    
    def get_transaction_count(self, chain: str, address: str, block: str = "latest") -> int:
        """
        Get transaction count (nonce).
        
        Args:
            chain: Chain name
            address: Address
            block: Block number or "latest"
            
        Returns:
            Transaction count
        """
        response = self._make_request(
            chain=chain,
            method=RPCMethod.ETH_GET_TRANSACTION_COUNT.value,
            params=[address, block]
        )
        
        if response.result:
            return int(response.result, 16)
        return 0
    
    def _get_chain_id(self, chain: str) -> int:
        """
        Get chain ID.
        
        Args:
            chain: Chain name
            
        Returns:
            Chain ID
        """
        # Map chain names to IDs
        chain_ids = {
            "Ethereum": 1,
            "Binance": 56,
            "Arbitrum": 42161,
            "Base": 8453,
            "Polygon": 137,
            "Avalanche": 43114,
            "Optimism": 10,
            "Fantom": 250
        }
        
        return chain_ids.get(chain, 1)
    
    def multicall(
        self,
        chain: str,
        calls: List[Dict[str, Any]],
        block: str = "latest"
    ) -> List[Any]:
        """
        Execute multiple calls in a single request using multicall.
        
        Args:
            chain: Chain name
            calls: List of call specifications
            block: Block number or "latest"
            
        Returns:
            List of results
        """
        # This would require implementing multicall contract calls
        # For now, execute calls sequentially
        results = []
        for call in calls:
            try:
                result = self.call_contract(
                    chain=chain,
                    to=call["target"],
                    data=call["callData"],
                    block=block
                )
                results.append(result)
            except Exception as e:
                results.append(f"Error: {e}")
        
        return results