#!/usr/bin/env python3
"""
Protocol-aware contract wrapper that uses the protocol catalog for smart interactions.
"""

import json
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass

from .catalog import ProtocolType, ContractRole, ContractMethod, catalog
from .registry import ProtocolDefinition, registry
from ..core.contract import Contract
from ..core.chain import Chain


class ProtocolContract:
    """
    Protocol-aware contract wrapper.
    Extends the basic Contract with protocol-specific knowledge.
    """
    
    def __init__(self, contract: Contract, protocol_name: Optional[str] = None, role: Optional[str] = None):
        """
        Initialize protocol contract.
        
        Args:
            contract: Base Contract instance
            protocol_name: Known protocol name (auto-detected if None)
            role: Contract role within protocol (auto-detected if None)
        """
        self.contract = contract
        self._protocol_name = protocol_name
        self._role = role
        self._protocol: Optional[ProtocolDefinition] = None
        self._template = None
        
        # Auto-detect protocol if not provided
        if not self._protocol_name:
            self._detect_protocol()
    
    def _detect_protocol(self):
        """Auto-detect protocol from contract address."""
        result = registry.find_protocol_by_address(
            self.contract.address,
            self.contract.chain.name
        )
        
        if result:
            self._protocol_name, self._protocol, self._role = result
            self._template = registry.get_template_for_contract(
                self._protocol_name,
                self._role
            )
    
    @property
    def protocol_name(self) -> Optional[str]:
        """Get protocol name."""
        return self._protocol_name
    
    @property
    def protocol(self) -> Optional[ProtocolDefinition]:
        """Get protocol definition."""
        if not self._protocol and self._protocol_name:
            self._protocol = registry.get_protocol(self._protocol_name)
        return self._protocol
    
    @property
    def role(self) -> Optional[str]:
        """Get contract role."""
        return self._role
    
    @property
    def template(self):
        """Get protocol template."""
        if not self._template and self._protocol_name and self._role:
            self._template = registry.get_template_for_contract(
                self._protocol_name,
                self._role
            )
        return self._template
    
    @property
    def protocol_type(self) -> Optional[ProtocolType]:
        """Get protocol type."""
        if self.protocol:
            return self.protocol.protocol_type
        return None
    
    def get_available_methods(self) -> List[ContractMethod]:
        """Get list of available methods for this contract type."""
        if self.template:
            return self.template.methods
        return []
    
    def get_methods_by_category(self, category: str) -> List[ContractMethod]:
        """Get methods by category (read, write, query, admin)."""
        return [m for m in self.get_available_methods() if m.category == category]
    
    def get_read_methods(self) -> List[ContractMethod]:
        """Get all read methods."""
        return self.get_methods_by_category("read")
    
    def get_write_methods(self) -> List[ContractMethod]:
        """Get all write methods."""
        return self.get_methods_by_category("write")
    
    def find_method(self, name: str) -> Optional[ContractMethod]:
        """Find a method by name."""
        for method in self.get_available_methods():
            if method.name == name:
                return method
        return None
    
    def call_protocol_method(
        self,
        method_name: str,
        params: Optional[List[Any]] = None,
        **kwargs
    ) -> Any:
        """
        Call a protocol-specific method.
        
        Args:
            method_name: Method name
            params: Method parameters
            **kwargs: Additional arguments for contract.call()
            
        Returns:
            Method result
        """
        method = self.find_method(method_name)
        if not method:
            raise ValueError(f"Method '{method_name}' not found for {self._protocol_name}/{self._role}")
        
        # Use provided params or example params
        call_params = params if params is not None else method.example_params
        
        return self.contract.call(method_name, call_params or [], **kwargs)
    
    # === DEX-specific methods ===
    
    def get_reserves(self) -> Optional[Dict[str, Any]]:
        """Get pair reserves (for DEX pairs)."""
        if self._role != "pair":
            return None
        
        try:
            result = self.call_protocol_method("getReserves")
            if result and len(result) >= 3:
                return {
                    "reserve0": result[0],
                    "reserve1": result[1],
                    "blockTimestampLast": result[2]
                }
        except Exception:
            pass
        
        return None
    
    def get_token_pair(self) -> Optional[tuple]:
        """Get token pair addresses (for DEX pairs)."""
        if self._role != "pair":
            return None
        
        try:
            token0 = self.call_protocol_method("token0")
            token1 = self.call_protocol_method("token1")
            return (token0, token1)
        except Exception:
            pass
        
        return None
    
    def get_swap_quote(
        self,
        amount_in: int,
        path: List[str],
        is_exact_input: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get swap quote (for DEX routers).
        
        Args:
            amount_in: Input amount
            path: Token path [token_in, ..., token_out]
            is_exact_input: True for exact input, False for exact output
            
        Returns:
            Quote information
        """
        if self._role != "router":
            return None
        
        try:
            if is_exact_input:
                result = self.call_protocol_method("getAmountsOut", [amount_in, path])
                if result and len(result) > 0:
                    return {
                        "amount_in": amount_in,
                        "amount_out": result[-1],
                        "path": path,
                        "amounts": result
                    }
            else:
                # For exact output, we need amount_out
                # This would need separate handling
                pass
        except Exception:
            pass
        
        return None
    
    def swap_exact_tokens_for_tokens(
        self,
        amount_in: int,
        amount_out_min: int,
        path: List[str],
        to: str,
        deadline: Optional[int] = None,
        private_key: str = None
    ) -> Optional[str]:
        """
        Execute swap (for DEX routers).
        
        Args:
            amount_in: Input amount
            amount_out_min: Minimum output amount
            path: Token path
            to: Recipient address
            deadline: Transaction deadline
            private_key: Private key for signing
            
        Returns:
            Transaction hash
        """
        if self._role != "router":
            return None
        
        import time
        if deadline is None:
            deadline = int(time.time()) + 300  # 5 minutes
        
        try:
            return self.contract.call(
                "swapExactTokensForTokens",
                [amount_in, amount_out_min, path, to, deadline],
                private_key=private_key
            )
        except Exception as e:
            print(f"Swap failed: {e}")
            return None
    
    # === Lending-specific methods ===
    
    def supply(
        self,
        asset: str,
        amount: int,
        on_behalf_of: str,
        private_key: str = None
    ) -> Optional[str]:
        """
        Supply asset to lending pool.
        
        Args:
            asset: Asset address
            amount: Amount to supply
            on_behalf_of: Beneficiary address
            private_key: Private key for signing
            
        Returns:
            Transaction hash
        """
        if self.protocol_type != ProtocolType.LENDING:
            return None
        
        try:
            return self.call_protocol_method(
                "supply",
                [asset, amount, on_behalf_of, 0],
                private_key=private_key
            )
        except Exception as e:
            print(f"Supply failed: {e}")
            return None
    
    def withdraw(
        self,
        asset: str,
        amount: int,
        to: str,
        private_key: str = None
    ) -> Optional[str]:
        """
        Withdraw asset from lending pool.
        
        Args:
            asset: Asset address
            amount: Amount to withdraw
            to: Recipient address
            private_key: Private key for signing
            
        Returns:
            Transaction hash
        """
        if self.protocol_type != ProtocolType.LENDING:
            return None
        
        try:
            return self.call_protocol_method(
                "withdraw",
                [asset, amount, to],
                private_key=private_key
            )
        except Exception as e:
            print(f"Withdraw failed: {e}")
            return None
    
    def borrow(
        self,
        asset: str,
        amount: int,
        interest_rate_mode: int = 2,  # 1=stable, 2=variable
        on_behalf_of: str = None,
        private_key: str = None
    ) -> Optional[str]:
        """
        Borrow from lending pool.
        
        Args:
            asset: Asset address
            amount: Amount to borrow
            interest_rate_mode: Interest rate mode
            on_behalf_of: Borrower address
            private_key: Private key for signing
            
        Returns:
            Transaction hash
        """
        if self.protocol_type != ProtocolType.LENDING:
            return None
        
        if on_behalf_of is None:
            on_behalf_of = self.contract.provider.get_address(private_key)
        
        try:
            return self.call_protocol_method(
                "borrow",
                [asset, amount, interest_rate_mode, 0, on_behalf_of],
                private_key=private_key
            )
        except Exception as e:
            print(f"Borrow failed: {e}")
            return None
    
    def get_user_account_data(self, user: str) -> Optional[Dict[str, Any]]:
        """
        Get user account data (for lending protocols).
        
        Args:
            user: User address
            
        Returns:
            Account data dictionary
        """
        if self.protocol_type != ProtocolType.LENDING:
            return None
        
        try:
            result = self.call_protocol_method("getUserAccountData", [user])
            if result and len(result) >= 6:
                return {
                    "totalCollateralETH": result[0],
                    "totalDebtETH": result[1],
                    "availableBorrowsETH": result[2],
                    "currentLiquidationThreshold": result[3],
                    "ltv": result[4],
                    "healthFactor": result[5]
                }
        except Exception:
            pass
        
        return None
    
    # === Bridge-specific methods ===
    
    def bridge_tokens(
        self,
        token: str,
        amount: int,
        dest_chain_id: int,
        recipient: str,
        private_key: str = None
    ) -> Optional[str]:
        """
        Bridge tokens to another chain.
        
        Args:
            token: Token address
            amount: Amount to bridge
            dest_chain_id: Destination chain ID
            recipient: Recipient address on destination chain
            private_key: Private key for signing
            
        Returns:
            Transaction hash
        """
        if self.protocol_type != ProtocolType.BRIDGE:
            return None
        
        try:
            return self.call_protocol_method(
                "bridge",
                [token, amount, dest_chain_id, recipient],
                private_key=private_key
            )
        except Exception as e:
            print(f"Bridge failed: {e}")
            return None
    
    def estimate_bridge_fees(
        self,
        token: str,
        amount: int,
        dest_chain_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Estimate bridge fees.
        
        Args:
            token: Token address
            amount: Amount to bridge
            dest_chain_id: Destination chain ID
            
        Returns:
            Fee estimation
        """
        if self.protocol_type != ProtocolType.BRIDGE:
            return None
        
        try:
            result = self.call_protocol_method(
                "estimateFees",
                [token, amount, dest_chain_id, False, b""]
            )
            if result and len(result) >= 2:
                return {
                    "nativeFee": result[0],
                    "lzTokenFee": result[1]
                }
        except Exception:
            pass
        
        return None
    
    # === Oracle-specific methods ===
    
    def get_price(self) -> Optional[Dict[str, Any]]:
        """
        Get price from oracle.
        
        Returns:
            Price information
        """
        if self.protocol_type != ProtocolType.ORACLE:
            return None
        
        try:
            # Try latestRoundData first (more complete)
            result = self.call_protocol_method("latestRoundData")
            if result and len(result) >= 5:
                decimals = self.call_protocol_method("decimals")
                description = self.call_protocol_method("description")
                
                return {
                    "roundId": result[0],
                    "answer": result[1],
                    "startedAt": result[2],
                    "updatedAt": result[3],
                    "answeredInRound": result[4],
                    "decimals": decimals,
                    "description": description
                }
        except Exception:
            # Fallback to latestAnswer
            try:
                answer = self.call_protocol_method("latestAnswer")
                decimals = self.call_protocol_method("decimals")
                
                return {
                    "answer": answer,
                    "decimals": decimals
                }
            except Exception:
                pass
        
        return None
    
    # === Staking-specific methods ===
    
    def stake(
        self,
        amount: int,
        private_key: str = None
    ) -> Optional[str]:
        """
        Stake tokens.
        
        Args:
            amount: Amount to stake
            private_key: Private key for signing
            
        Returns:
            Transaction hash
        """
        if self.protocol_type != ProtocolType.YIELD:
            return None
        
        try:
            return self.call_protocol_method("stake", [amount], private_key=private_key)
        except Exception as e:
            print(f"Stake failed: {e}")
            return None
    
    def get_staking_rewards(self, account: str) -> Optional[int]:
        """
        Get earned staking rewards.
        
        Args:
            account: Account address
            
        Returns:
            Earned rewards
        """
        if self.protocol_type != ProtocolType.YIELD:
            return None
        
        try:
            return self.call_protocol_method("earned", [account])
        except Exception:
            pass
        
        return None
    
    # === Utility methods ===
    
    def get_contract_info(self) -> Dict[str, Any]:
        """Get comprehensive contract information."""
        info = {
            "address": self.contract.address,
            "chain": self.contract.chain.name,
            "is_contract": self.contract.is_contract()
        }
        
        if self.protocol:
            info["protocol"] = {
                "name": self.protocol.name,
                "type": self.protocol.protocol_type.value,
                "version": self.protocol.version,
                "website": self.protocol.website,
                "docs": self.protocol.docs
            }
        
        if self._role:
            info["role"] = self._role
        
        # Add available methods
        methods = self.get_available_methods()
        if methods:
            info["methods"] = [
                {
                    "name": m.name,
                    "signature": m.signature,
                    "description": m.description,
                    "category": m.category,
                    "state_mutability": m.state_mutability
                }
                for m in methods
            ]
        
        # Try to get common ERC20 info
        try:
            info["token"] = {}
            for method_name in ["name", "symbol", "decimals", "totalSupply"]:
                try:
                    result = self.contract.call(method_name, [])
                    info["token"][method_name] = result
                except Exception:
                    pass
        except Exception:
            pass
        
        return info
    
    def __repr__(self) -> str:
        protocol_str = f" ({self._protocol_name}/{self._role})" if self._protocol_name else ""
        return f"ProtocolContract({self.contract.address[:10]}...{protocol_str})"