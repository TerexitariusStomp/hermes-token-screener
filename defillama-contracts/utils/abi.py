#!/usr/bin/env python3
"""
ABI Resolver for encoding/decoding smart contract calls.
"""

import json
import hashlib
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
from dataclasses import dataclass


@dataclass
class MethodSignature:
    """Method signature information."""
    name: str
    inputs: List[Dict[str, str]]
    outputs: List[Dict[str, str]]
    signature: str


class ABIResolver:
    """
    Resolves and manages contract ABIs.
    
    Usage:
        # Initialize resolver
        resolver = ABIResolver()
        
        # Get ABI for contract
        abi = resolver.get_abi("Ethereum", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984")
        
        # Encode method call
        encoded = resolver.encode_method_call("balanceOf(address)", ["0x..."])
    """
    
    # Common method signatures
    COMMON_METHODS = {
        "balanceOf(address)": "0x70a08231",
        "totalSupply()": "0x18160ddd",
        "decimals()": "0x313ce567",
        "symbol()": "0x95d89b41",
        "name()": "0x06fdde03",
        "transfer(address,uint256)": "0xa9059cbb",
        "transferFrom(address,address,uint256)": "0x23b872dd",
        "approve(address,uint256)": "0x095ea7b3",
        "allowance(address,address)": "0xdd62ed3e",
        "owner()": "0x8da5cb5b",
        "paused()": "0x5c975abb",
        "getReserves()": "0x0902f1ac",
        "token0()": "0x0dfe1681",
        "token1()": "0xd21220a7",
        "factory()": "0xc45a0155",
        "WETH()": "0xad5c4648",
        "allPairsLength()": "0x574f2ba3",
        "allPairs(uint256)": "0x1e3dd18b",
        "getPair(address,address)": "0xe6a43905",
        "pairFor(address,address,address)": "0x481c6e28",
        "getAmountOut(uint256,uint256,uint256)": "0x054d50d4",
        "getAmountIn(uint256,uint256,uint256)": "0x85f8c259",
        "getAmountsOut(uint256,address[])": "0xd06ca61f",
        "getAmountsIn(uint256,address[])": "0x1f00ca74",
        "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)": "0x38ed1739",
        "swapTokensForExactTokens(uint256,uint256,address[],address,uint256)": "0x8803dbee",
        "swapExactETHForTokens(uint256,address[],address,uint256)": "0x7ff36ab5",
        "swapTokensForExactETH(uint256,uint256,address[],address,uint256)": "0x4a25d94a",
        "swapExactTokensForETH(uint256,uint256,address[],address,uint256)": "0x18cbafe5",
        "swapETHForExactTokens(uint256,address[],address,uint256)": "0xfb3bdb41",
        "addLiquidity(address,address,uint256,uint256,uint256,uint256,address,uint256)": "0xe8e33700",
        "removeLiquidity(address,address,uint256,uint256,uint256,address,uint256)": "0xbaa2abde",
        "addLiquidityETH(address,uint256,uint256,uint256,address,uint256)": "0xf305d719",
        "removeLiquidityETH(address,uint256,uint256,uint256,address,uint256)": "0x02751cec",
        "removeLiquidityWithPermit(address,address,uint256,uint256,uint256,address,uint256,bool,uint8,bytes32,bytes32)": "0x2195995c",
        "removeLiquidityETHWithPermit(address,uint256,uint256,uint256,address,uint256,bool,uint8,bytes32,bytes32)": "0xded9382a",
        "removeLiquidityETHSupportingFeeOnTransferTokens(address,uint256,uint256,uint256,address,uint256)": "0x5b0d5984",
        "removeLiquidityETHWithPermitSupportingFeeOnTransferTokens(address,uint256,uint256,uint256,address,uint256,bool,uint8,bytes32,bytes32)": "0x5b0d5984",
        "swapExactTokensForTokensSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)": "0x5ae401dc",
        "swapExactETHForTokensSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)": "0xb6f9de95",
        "swapExactTokensForETHSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)": "0x791ac947",
    }
    
    # Common event signatures
    COMMON_EVENTS = {
        "Transfer(address,address,uint256)": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
        "Approval(address,address,uint256)": "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925",
        "Swap(address,uint256,uint256,uint256,uint256,address)": "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
        "Sync(uint112,uint112)": "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1",
        "Mint(address,uint256,uint256)": "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f",
        "Burn(address,uint256,uint256,address)": "0xdccd412f0b1252819cb1fd330b93224ca42612892bb3f4f789976e6d81936496",
        "PairCreated(address,address,address,uint256)": "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9",
    }
    
    def __init__(self):
        """Initialize ABI resolver."""
        # Cache for ABIs
        self._abi_cache: Dict[str, List[Dict]] = {}
        
        # ABI sources
        self.abi_sources = [
            self._get_abi_from_etherscan,
            self._get_abi_from_sourcify,
            self._get_abi_from_blockscout,
        ]
    
    def get_abi(self, chain: str, address: str) -> List[Dict]:
        """
        Get ABI for a contract.
        
        Args:
            chain: Chain name
            address: Contract address
            
        Returns:
            Contract ABI
        """
        cache_key = f"{chain}:{address}"
        
        if cache_key in self._abi_cache:
            return self._abi_cache[cache_key]
        
        # Try to get ABI from sources
        for source in self.abi_sources:
            try:
                abi = source(chain, address)
                if abi:
                    self._abi_cache[cache_key] = abi
                    return abi
            except:
                continue
        
        # Return empty ABI if not found
        return []
    
    def _get_abi_from_etherscan(self, chain: str, address: str) -> List[Dict]:
        """Get ABI from Etherscan-like explorers."""
        # Map chain names to explorer APIs
        explorer_apis = {
            "Ethereum": "https://api.etherscan.io/api",
            "Binance": "https://api.bscscan.com/api",
            "Polygon": "https://api.polygonscan.com/api",
            "Arbitrum": "https://api.arbiscan.io/api",
            "Optimism": "https://api-optimistic.etherscan.io/api",
            "Avalanche": "https://api.snowtrace.io/api",
            "Fantom": "https://api.ftmscan.com/api",
        }
        
        api_url = explorer_apis.get(chain)
        if not api_url:
            return []
        
        # This would require API keys for each explorer
        # For now, return empty
        return []
    
    def _get_abi_from_sourcify(self, chain: str, address: str) -> List[Dict]:
        """Get ABI from Sourcify."""
        # Sourcify provides verified contract ABIs
        # This would require implementing Sourcify API calls
        return []
    
    def _get_abi_from_blockscout(self, chain: str, address: str) -> List[Dict]:
        """Get ABI from Blockscout."""
        # Blockscout provides verified contract ABIs
        # This would require implementing Blockscout API calls
        return []
    
    def encode_method_call(self, signature: str, params: List[Any]) -> str:
        """
        Encode method call.
        
        Args:
            signature: Method signature (e.g., "balanceOf(address)")
            params: Method parameters
            
        Returns:
            Encoded method call as hex string
        """
        # Get method selector
        selector = self._get_method_selector(signature)
        
        # Encode parameters
        encoded_params = self._encode_params(signature, params)
        
        return selector + encoded_params
    
    def _get_method_selector(self, signature: str) -> str:
        """
        Get method selector (4-byte signature).
        
        Args:
            signature: Method signature
            
        Returns:
            Method selector as hex string
        """
        # Check if it's a common method
        if signature in self.COMMON_METHODS:
            return self.COMMON_METHODS[signature]
        
        # Calculate selector
        hash_bytes = hashlib.sha3_256(signature.encode()).digest()
        selector = hash_bytes[:4].hex()
        
        return "0x" + selector
    
    def _encode_params(self, signature: str, params: List[Any]) -> str:
        """
        Encode method parameters.
        
        Args:
            signature: Method signature
            params: Parameters to encode
            
        Returns:
            Encoded parameters as hex string
        """
        # Parse signature to get parameter types
        param_types = self._parse_signature_params(signature)
        
        if len(param_types) != len(params):
            raise ValueError(f"Parameter count mismatch: expected {len(param_types)}, got {len(params)}")
        
        encoded = ""
        for i, (param_type, param_value) in enumerate(zip(param_types, params)):
            encoded += self._encode_param(param_type, param_value)
        
        return encoded
    
    def _parse_signature_params(self, signature: str) -> List[str]:
        """
        Parse parameter types from method signature.
        
        Args:
            signature: Method signature
            
        Returns:
            List of parameter types
        """
        # Extract parameter types from signature
        # Format: methodName(type1,type2,...)
        start = signature.find("(") + 1
        end = signature.find(")")
        
        if start == 0 or end == -1:
            return []
        
        params_str = signature[start:end]
        if not params_str:
            return []
        
        return [p.strip() for p in params_str.split(",")]
    
    def _encode_param(self, param_type: str, param_value: Any) -> str:
        """
        Encode a single parameter.
        
        Args:
            param_type: Parameter type
            param_value: Parameter value
            
        Returns:
            Encoded parameter as hex string
        """
        # Handle different parameter types
        if param_type == "address":
            # Address: 20 bytes, padded to 32 bytes
            if isinstance(param_value, str):
                if param_value.startswith("0x"):
                    param_value = param_value[2:]
                return param_value.lower().zfill(64)
            else:
                raise ValueError(f"Invalid address: {param_value}")
        
        elif param_type == "uint256" or param_type == "uint":
            # uint256: 32 bytes
            if isinstance(param_value, int):
                return hex(param_value)[2:].zfill(64)
            else:
                raise ValueError(f"Invalid uint256: {param_value}")
        
        elif param_type == "bool":
            # bool: 32 bytes (0 or 1)
            if isinstance(param_value, bool):
                return "1".zfill(64) if param_value else "0".zfill(64)
            else:
                raise ValueError(f"Invalid bool: {param_value}")
        
        elif param_type == "bytes32":
            # bytes32: 32 bytes
            if isinstance(param_value, str):
                if param_value.startswith("0x"):
                    param_value = param_value[2:]
                return param_value.zfill(64)
            else:
                raise ValueError(f"Invalid bytes32: {param_value}")
        
        elif param_type == "bytes":
            # bytes: dynamic length
            if isinstance(param_value, str):
                if param_value.startswith("0x"):
                    param_value = param_value[2:]
                # Encode length + data
                length = len(param_value) // 2
                return hex(length)[2:].zfill(64) + param_value
            else:
                raise ValueError(f"Invalid bytes: {param_value}")
        
        elif param_type == "string":
            # string: dynamic length
            if isinstance(param_value, str):
                # Encode as bytes
                bytes_value = param_value.encode('utf-8')
                length = len(bytes_value)
                # Pad to 32-byte boundary
                padded = bytes_value.hex()
                if len(padded) % 64 != 0:
                    padded = padded.ljust((len(padded) // 64 + 1) * 64, '0')
                return hex(length)[2:].zfill(64) + padded
            else:
                raise ValueError(f"Invalid string: {param_value}")
        
        elif param_type.startswith("address[]"):
            # Array of addresses
            if isinstance(param_value, list):
                # Encode array length
                encoded = hex(len(param_value))[2:].zfill(64)
                # Encode each address
                for addr in param_value:
                    encoded += self._encode_param("address", addr)
                return encoded
            else:
                raise ValueError(f"Invalid address array: {param_value}")
        
        elif param_type.startswith("uint256[]"):
            # Array of uint256
            if isinstance(param_value, list):
                # Encode array length
                encoded = hex(len(param_value))[2:].zfill(64)
                # Encode each uint256
                for val in param_value:
                    encoded += self._encode_param("uint256", val)
                return encoded
            else:
                raise ValueError(f"Invalid uint256 array: {param_value}")
        
        else:
            # Unknown type, try to encode as bytes
            if isinstance(param_value, str):
                if param_value.startswith("0x"):
                    param_value = param_value[2:]
                return param_value.zfill(64)
            else:
                raise ValueError(f"Unsupported parameter type: {param_type}")
    
    def decode_method_result(self, outputs: List[Dict], data: str) -> Any:
        """
        Decode method result.
        
        Args:
            outputs: Method output definitions
            data: Encoded result data
            
        Returns:
            Decoded result
        """
        if not data or data == "0x":
            return None
        
        # Remove 0x prefix
        if data.startswith("0x"):
            data = data[2:]
        
        # If no outputs defined, return raw data
        if not outputs:
            return "0x" + data
        
        # Decode based on output types
        if len(outputs) == 1:
            return self._decode_param(outputs[0]["type"], data)
        else:
            # Multiple outputs - would need tuple decoding
            # For now, return raw data
            return "0x" + data
    
    def _decode_param(self, param_type: str, data: str) -> Any:
        """
        Decode a single parameter.
        
        Args:
            param_type: Parameter type
            data: Encoded data
            
        Returns:
            Decoded value
        """
        if param_type == "address":
            # Address: last 20 bytes
            if len(data) >= 40:
                return "0x" + data[-40:]
            else:
                return "0x" + data.zfill(40)
        
        elif param_type == "uint256" or param_type == "uint":
            # uint256: 32 bytes
            if len(data) >= 64:
                return int(data[:64], 16)
            else:
                return int(data, 16)
        
        elif param_type == "bool":
            # bool: 32 bytes
            if len(data) >= 64:
                return data[:64] != "0" * 64
            else:
                return data != "0" * len(data)
        
        elif param_type == "bytes32":
            # bytes32: 32 bytes
            if len(data) >= 64:
                return "0x" + data[:64]
            else:
                return "0x" + data.zfill(64)
        
        elif param_type == "string":
            # string: dynamic length
            if len(data) >= 64:
                length = int(data[:64], 16)
                string_data = data[64:64 + length * 2]
                # Convert hex to string
                bytes_data = bytes.fromhex(string_data)
                return bytes_data.decode('utf-8').rstrip('\x00')
            else:
                return ""
        
        elif param_type == "bytes":
            # bytes: dynamic length
            if len(data) >= 64:
                length = int(data[:64], 16)
                bytes_data = data[64:64 + length * 2]
                return "0x" + bytes_data
            else:
                return "0x" + data
        
        else:
            # Unknown type, return raw data
            return "0x" + data
    
    def create_event_signature(self, event_info: Dict) -> str:
        """
        Create event signature hash.
        
        Args:
            event_info: Event information from ABI
            
        Returns:
            Event signature hash
        """
        # Create event signature string
        inputs = event_info.get("inputs", [])
        input_types = [inp["type"] for inp in inputs]
        signature = f"{event_info.get('name', '')}({','.join(input_types)})"
        
        # Check if it's a common event
        if signature in self.COMMON_EVENTS:
            return self.COMMON_EVENTS[signature]
        
        # Calculate keccak256 hash
        hash_bytes = hashlib.sha3_256(signature.encode()).digest()
        return "0x" + hash_bytes.hex()
    
    def decode_event_log(self, event_info: Dict, log: Dict) -> Dict:
        """
        Decode event log.
        
        Args:
            event_info: Event information from ABI
            log: Raw log data
            
        Returns:
            Decoded event
        """
        # This is a simplified implementation
        # In production, you'd properly decode indexed and non-indexed parameters
        
        decoded = {
            "event": event_info.get("name"),
            "address": log.get("address"),
            "transactionHash": log.get("transactionHash"),
            "blockNumber": log.get("blockNumber"),
            "args": {}
        }
        
        # Decode topics (indexed parameters)
        topics = log.get("topics", [])
        data = log.get("data", "0x")
        
        inputs = event_info.get("inputs", [])
        topic_index = 1  # Skip event signature topic
        
        for i, inp in enumerate(inputs):
            if inp.get("indexed"):
                # Indexed parameter in topics
                if topic_index < len(topics):
                    decoded["args"][inp["name"]] = self._decode_param(
                        inp["type"],
                        topics[topic_index][2:]  # Remove 0x prefix
                    )
                    topic_index += 1
            else:
                # Non-indexed parameter in data
                # This is simplified - proper implementation would handle offset/length
                if data and data != "0x":
                    decoded["args"][inp["name"]] = self._decode_param(
                        inp["type"],
                        data[2:]  # Remove 0x prefix
                    )
        
        return decoded