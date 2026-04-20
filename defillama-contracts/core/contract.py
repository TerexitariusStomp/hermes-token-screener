#!/usr/bin/env python3
"""
Contract abstraction for interacting with smart contracts.
"""

import json
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum

from ..chains.chain import Chain
from ..providers.rpc import RPCProvider
from ..utils.abi import ABIResolver


class CallType(Enum):
    """Type of contract call."""
    READ = "read"
    WRITE = "write"
    ESTIMATE_GAS = "estimate_gas"


@dataclass
class CallResult:
    """Result of a contract call."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    gas_used: Optional[int] = None
    transaction_hash: Optional[str] = None


class Contract:
    """
    Represents a smart contract on a specific chain.
    
    Usage:
        # Create contract instance
        contract = Contract(chain, address, provider)
        
        # Call read methods
        balance = contract.call("balanceOf", ["0x..."])
        
        # Call write methods (requires private key)
        tx_hash = contract.call("transfer", ["0x...", 1000], private_key="0x...")
    """
    
    def __init__(
        self,
        chain: Chain,
        address: str,
        provider: RPCProvider,
        abi: Optional[List[Dict]] = None
    ):
        """
        Initialize a contract instance.
        
        Args:
            chain: Chain instance
            address: Contract address
            provider: RPC provider instance
            abi: Contract ABI (optional, will be fetched if not provided)
        """
        self.chain = chain
        self.address = address
        self.provider = provider
        self.abi_resolver = ABIResolver()
        
        # Load ABI if not provided
        if abi:
            self.abi = abi
        else:
            self.abi = self.abi_resolver.get_abi(chain.name, address)
        
        # Cache for method signatures
        self._method_signatures: Dict[str, Dict] = {}
        self._event_signatures: Dict[str, Dict] = {}
        
        # Parse ABI
        if self.abi:
            self._parse_abi()
    
    def _parse_abi(self):
        """Parse ABI to extract method and event signatures."""
        for item in self.abi:
            if item.get("type") == "function":
                name = item["name"]
                inputs = item.get("inputs", [])
                outputs = item.get("outputs", [])
                
                # Create method signature
                input_types = [inp["type"] for inp in inputs]
                signature = f"{name}({','.join(input_types)})"
                
                self._method_signatures[name] = {
                    "signature": signature,
                    "inputs": inputs,
                    "outputs": outputs,
                    "stateMutability": item.get("stateMutability", "nonpayable")
                }
            
            elif item.get("type") == "event":
                name = item["name"]
                inputs = item.get("inputs", [])
                
                self._event_signatures[name] = {
                    "inputs": inputs,
                    "anonymous": item.get("anonymous", False)
                }
    
    def call(
        self,
        method: str,
        params: List[Any] = None,
        abi: Optional[List[Dict]] = None,
        private_key: Optional[str] = None,
        gas_limit: Optional[int] = None,
        gas_price: Optional[int] = None,
        value: int = 0
    ) -> Any:
        """
        Call a contract method.
        
        Args:
            method: Method name
            params: Method parameters
            abi: Override ABI for this call
            private_key: Private key for write operations
            gas_limit: Gas limit for write operations
            gas_price: Gas price for write operations
            value: ETH value to send with transaction
            
        Returns:
            Method result for read operations, transaction hash for write operations
        """
        if params is None:
            params = []
        
        # Use provided ABI or default
        call_abi = abi or self.abi
        
        # Find method in ABI
        method_info = self._find_method(method, call_abi)
        if not method_info:
            raise ValueError(f"Method {method} not found in ABI")
        
        # Determine call type
        is_write = method_info.get("stateMutability") not in ["view", "pure"]
        
        if is_write and not private_key:
            raise ValueError("Private key required for write operations")
        
        # Encode method call
        encoded_data = self.abi_resolver.encode_method_call(
            method_info["signature"],
            params
        )
        
        if is_write:
            # Write operation
            return self._execute_write(
                encoded_data=encoded_data,
                private_key=private_key,
                gas_limit=gas_limit,
                gas_price=gas_price,
                value=value
            )
        else:
            # Read operation
            return self._execute_read(encoded_data)
    
    def _find_method(self, method_name: str, abi: List[Dict]) -> Optional[Dict]:
        """Find method in ABI."""
        for item in abi:
            if item.get("type") == "function" and item.get("name") == method_name:
                return item
        return None
    
    def _execute_read(self, encoded_data: str) -> Any:
        """Execute a read-only call."""
        try:
            result = self.provider.call_contract(
                chain=self.chain.name,
                to=self.address,
                data=encoded_data
            )
            
            # Decode result
            if result and result != "0x":
                # Find method from encoded data
                method_sig = encoded_data[:10]  # First 4 bytes (8 hex chars + 0x)
                method_info = self._find_method_by_signature(method_sig)
                
                if method_info:
                    return self.abi_resolver.decode_method_result(
                        method_info["outputs"],
                        result
                    )
                else:
                    # Return raw result
                    return result
            
            return None
            
        except Exception as e:
            raise RuntimeError(f"Read call failed: {e}")
    
    def _execute_write(
        self,
        encoded_data: str,
        private_key: str,
        gas_limit: Optional[int] = None,
        gas_price: Optional[int] = None,
        value: int = 0
    ) -> str:
        """Execute a write operation."""
        try:
            # Estimate gas if not provided
            if gas_limit is None:
                gas_limit = self.provider.estimate_gas(
                    chain=self.chain.name,
                    to=self.address,
                    data=encoded_data,
                    value=value
                )
            
            # Get gas price if not provided
            if gas_price is None:
                gas_price = self.provider.get_gas_price(self.chain.name)
            
            # Send transaction
            tx_hash = self.provider.send_transaction(
                chain=self.chain.name,
                to=self.address,
                data=encoded_data,
                private_key=private_key,
                gas_limit=gas_limit,
                gas_price=gas_price,
                value=value
            )
            
            return CallResult(
                success=True,
                transaction_hash=tx_hash,
                gas_used=gas_limit
            )
            
        except Exception as e:
            return CallResult(
                success=False,
                error=str(e)
            )
    
    def _find_method_by_signature(self, signature: str) -> Optional[Dict]:
        """Find method by its 4-byte signature."""
        for method_name, method_info in self._method_signatures.items():
            # Calculate 4-byte signature
            import hashlib
            sig_bytes = hashlib.sha3_256(method_info["signature"].encode()).digest()[:4]
            if sig_bytes.hex() == signature[2:]:  # Remove 0x prefix
                return method_info
        return None
    
    def get_events(
        self,
        event_name: str,
        from_block: Union[int, str] = "latest",
        to_block: Union[int, str] = "latest",
        topics: List[str] = None
    ) -> List[Dict]:
        """
        Get contract events.
        
        Args:
            event_name: Event name
            from_block: Start block number or "latest"
            to_block: End block number or "latest"
            topics: Filter topics
            
        Returns:
            List of event logs
        """
        if event_name not in self._event_signatures:
            raise ValueError(f"Event {event_name} not found in ABI")
        
        # Create event signature hash
        event_info = self._event_signatures[event_name]
        event_sig = self.abi_resolver.create_event_signature(event_info)
        
        # Get logs
        logs = self.provider.get_logs(
            chain=self.chain.name,
            address=self.address,
            topics=[event_sig] + (topics or []),
            from_block=from_block,
            to_block=to_block
        )
        
        # Decode logs
        decoded_logs = []
        for log in logs:
            decoded = self.abi_resolver.decode_event_log(event_info, log)
            decoded_logs.append(decoded)
        
        return decoded_logs
    
    def get_balance(self, token_address: Optional[str] = None) -> int:
        """
        Get balance of this contract.
        
        Args:
            token_address: Token address for ERC20 balance, None for native balance
            
        Returns:
            Balance in wei
        """
        if token_address:
            # ERC20 balance
            token_contract = Contract(self.chain, token_address, self.provider)
            return token_contract.call("balanceOf", [self.address])
        else:
            # Native balance
            return self.provider.get_balance(self.chain.name, self.address)
    
    def get_code(self) -> str:
        """Get contract bytecode."""
        return self.provider.get_code(self.chain.name, self.address)
    
    def is_contract(self) -> bool:
        """Check if address is a contract."""
        code = self.get_code()
        return code and code != "0x"
    
    def get_implementation(self) -> Optional[str]:
        """
        Get implementation address for proxy contracts.
        
        Returns:
            Implementation address or None
        """
        # Try common proxy patterns
        proxy_slots = [
            "0x360894a13ba1a3210667c828492db7824c8b451867c520b4274240117240117240",  # EIP-1967
            "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3",  # OpenZeppelin
        ]
        
        for slot in proxy_slots:
            try:
                result = self.provider.get_storage_at(
                    chain=self.chain.name,
                    address=self.address,
                    position=slot
                )
                
                if result and result != "0x" + "0" * 64:
                    # Extract address from storage
                    impl_address = "0x" + result[-40:]
                    if self.provider.get_code(self.chain.name, impl_address) != "0x":
                        return impl_address
            except:
                continue
        
        return None
    
    def __str__(self):
        return f"Contract({self.chain.name}:{self.address[:10]}...)"
    
    def __repr__(self):
        return f"<Contract chain={self.chain.name} address={self.address}>"