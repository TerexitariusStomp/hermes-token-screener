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
            db_path = (
                Path.home() / ".hermes" / "data" / "defillama_verified_contracts.db"
            )

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
        self, chain: str, status: str = "deployed", limit: Optional[int] = None
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
                verification_time=c.get("verification_time"),
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
            chain=chain_obj, address=address, provider=self.rpc_provider
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
            block_time=chain_config.get("block_time", 12),
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
        limit: int = 50,
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
                verification_time=c.get("verification_time"),
            )
            for c in contracts
        ]

    def batch_call(
        self, calls: List[Dict[str, Any]], chain: Optional[str] = None
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
                results.append(
                    {
                        "error": f"Contract not found: {call_chain}:{call_spec['address']}"
                    }
                )
                continue

            try:
                result = contract.call(
                    method=call_spec["method"],
                    params=call_spec.get("params", []),
                    abi=call_spec.get("abi"),
                )
                results.append(
                    {
                        "chain": call_chain,
                        "address": call_spec["address"],
                        "method": call_spec["method"],
                        "result": result,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "chain": call_chain,
                        "address": call_spec["address"],
                        "method": call_spec["method"],
                        "error": str(e),
                    }
                )

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
        format: str = "json",
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
                vals = ", ".join(
                    [f"'{v}'" if isinstance(v, str) else str(v) for v in c.values()]
                )
                lines.append(
                    f"INSERT INTO verified_contracts ({cols}) VALUES ({vals});"
                )
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
            "chains": self.get_all_chains(),
        }

    def close(self):
        """Close database connections."""
        self.db.close()

    def classify_contract(self, chain: str, address: str) -> Dict[str, Any]:
        """
        Classify a contract by probing its on-chain interface.
        Works with ANY contract in the database.

        Args:
            chain: Chain name
            address: Contract address

        Returns:
            Dictionary with classification results including:
            - detected_categories: List of detected contract categories
            - suggested_template: Best matching template
            - suggested_role: Contract role (router, factory, pair, etc.)
            - suggested_protocol_type: Protocol type (DEX, lending, bridge, etc.)
            - confidence: Confidence score (0.0 to 1.0)
            - erc20_info: ERC20 token info if available
            - interaction_methods: List of methods to interact with
        """
        from ..protocols.classifier import ContractClassifier

        chain_obj = self.get_chain(chain)
        if not chain_obj:
            return {"error": f"Chain not found: {chain}"}

        classifier = ContractClassifier(rpc_provider=self.rpc_provider)
        classification = classifier.classify_contract(chain_obj, address)

        # Get interaction methods
        methods = classifier.get_interaction_methods(classification)

        return {
            "address": classification.address,
            "chain": classification.chain,
            "detected_categories": classification.detected_categories,
            "suggested_template": classification.suggested_template,
            "suggested_role": classification.suggested_role,
            "suggested_protocol_type": (
                classification.suggested_protocol_type.value
                if classification.suggested_protocol_type
                else None
            ),
            "confidence": classification.confidence,
            "erc20_info": classification.erc20_info,
            "bytecode_size": classification.bytecode_size,
            "is_proxy": classification.is_proxy,
            "interaction_methods": methods,
        }

    def get_smart_contract(self, chain: str, address: str) -> Optional[Any]:
        """
        Get a protocol-aware smart contract wrapper.
        Auto-detects protocol type and provides protocol-specific methods.
        Works with ANY contract in the database.

        Args:
            chain: Chain name
            address: Contract address

        Returns:
            ProtocolContract with smart methods, or None if not found
        """
        from ..protocols.contract import ProtocolContract
        from ..protocols.registry import registry

        # Get base contract
        contract = self.get_contract(chain, address)
        if not contract:
            return None

        # Try to create protocol-aware wrapper
        # First check if it's a registered protocol
        result = registry.find_protocol_by_address(address, chain)
        if result:
            name, protocol, role = result
            return ProtocolContract(contract, name, role)

        # Otherwise, try to auto-classify
        try:
            from ..protocols.classifier import ContractClassifier

            classifier = ContractClassifier(rpc_provider=self.rpc_provider)
            chain_obj = self.get_chain(chain)
            if chain_obj:
                classification = classifier.classify_contract(chain_obj, address)

                # Create protocol contract with detected template
                protocol_contract = ProtocolContract(contract)
                protocol_contract._role = classification.suggested_role

                return protocol_contract
        except Exception:
            pass

        # Return basic wrapper even without classification
        return ProtocolContract(contract)

    def classify_all_contracts(
        self, chain: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Classify all contracts in the database.
        This probes each contract on-chain to determine its type.

        Args:
            chain: Optional chain filter
            limit: Maximum number of contracts to classify

        Returns:
            List of classification results
        """
        from ..protocols.classifier import ContractClassifier

        classifier = ContractClassifier(rpc_provider=self.rpc_provider)
        results = []

        # Get contracts to classify
        if chain:
            contracts = self.get_chain_contracts(chain, "deployed", limit)
        else:
            # Get from all chains
            contracts = []
            for ch in self.get_all_chains():
                chain_contracts = self.get_chain_contracts(ch, "deployed")
                contracts.extend(chain_contracts)
                if limit and len(contracts) >= limit:
                    contracts = contracts[:limit]
                    break

        # Classify each contract
        for i, contract_info in enumerate(contracts):
            if limit and i >= limit:
                break

            chain_obj = self.get_chain(contract_info.chain)
            if not chain_obj:
                continue

            try:
                classification = classifier.classify_contract(
                    chain_obj, contract_info.address
                )
                results.append(
                    {
                        "address": classification.address,
                        "chain": classification.chain,
                        "detected_categories": classification.detected_categories,
                        "suggested_template": classification.suggested_template,
                        "suggested_role": classification.suggested_role,
                        "suggested_protocol_type": (
                            classification.suggested_protocol_type.value
                            if classification.suggested_protocol_type
                            else None
                        ),
                        "confidence": classification.confidence,
                        "erc20_info": classification.erc20_info,
                        "bytecode_size": classification.bytecode_size,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "address": contract_info.address,
                        "chain": contract_info.chain,
                        "error": str(e),
                    }
                )

        return results

    def get_contracts_by_type(
        self, chain: str, contract_type: str
    ) -> List[ContractInfo]:
        """
        Get contracts filtered by detected type.

        Args:
            chain: Chain name
            contract_type: Contract type (dex_router, dex_factory, dex_pair, lending, bridge, oracle, staking, vault)

        Returns:
            List of ContractInfo objects matching the type
        """
        all_contracts = self.get_chain_contracts(chain, "deployed")

        # For now, return all since we don't have type info in DB
        # In a full implementation, this would use cached classification results
        return all_contracts

    def get_contract_interaction_guide(
        self, chain: str, address: str
    ) -> Dict[str, Any]:
        """
        Get a complete guide on how to interact with any contract.
        Returns the exact methods, parameters, and examples needed.

        Args:
            chain: Chain name
            address: Contract address

        Returns:
            Complete interaction guide
        """
        classification = self.classify_contract(chain, address)

        if "error" in classification:
            return classification

        guide = {
            "contract": {
                "address": address,
                "chain": chain,
                "type": classification["suggested_protocol_type"],
                "role": classification["suggested_role"],
                "confidence": classification["confidence"],
            },
            "read_methods": [],
            "write_methods": [],
            "example_code": "",
            "notes": [],
        }

        # Organize methods by category
        for method in classification.get("interaction_methods", []):
            if method.get("source") == "template":
                method_info = {
                    "name": method["name"],
                    "signature": method.get("signature", ""),
                    "description": method.get("description", ""),
                    "gas_estimate": method.get("gas_estimate"),
                    "inputs": method.get("inputs", []),
                    "outputs": method.get("outputs", []),
                }

                if method.get("state_mutability") in ["view", "pure"]:
                    guide["read_methods"].append(method_info)
                else:
                    guide["write_methods"].append(method_info)

        # Add ERC20 info if available
        if classification.get("erc20_info"):
            erc20 = classification["erc20_info"]
            guide["token_info"] = {
                "name": erc20.get("name"),
                "symbol": erc20.get("symbol"),
                "decimals": erc20.get("decimals"),
                "totalSupply": erc20.get("totalSupply"),
            }

        # Generate example code
        guide["example_code"] = self._generate_example_code(
            chain, address, classification
        )

        return guide

    def _generate_example_code(
        self, chain: str, address: str, classification: Dict
    ) -> str:
        """Generate example Python code for interacting with a contract."""
        role = classification.get("suggested_role", "token")
        template = classification.get("suggested_template", "erc20")

        code = f"""from defillama_contracts import DefiLlamaContracts, ProtocolContract

# Initialize
client = DefiLlamaContracts()

# Get contract
contract = client.get_contract("{chain}", "{address}")
"""

        if role == "router":
            code += """
# DEX Router - Get swap quote
router = ProtocolContract(contract, "{protocol}", "router")
weth = router.call_protocol_method("WETH")
usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
quote = router.get_swap_quote(10**18, [weth, usdc])
print(f"Output: {{quote['amount_out']}}")

# Execute swap (need private key)
# tx = router.swap_exact_tokens_for_tokens(10**18, min_out, [weth, usdc], my_addr, private_key=key)
""".format(
                protocol=classification.get("suggested_protocol_type", "dex")
            )

        elif role == "pair":
            code += """
# DEX Pair - Get reserves and token info
pair = ProtocolContract(contract, "unknown", "pair")
token0 = pair.call_protocol_method("token0")
token1 = pair.call_protocol_method("token1")
reserves = pair.call_protocol_method("getReserves")
print(f"Token0: {{token0}}")
print(f"Token1: {{token1}}")
print(f"Reserves: {{reserves[0]}}, {{reserves[1]}}")
"""

        elif role == "factory":
            code += """
# DEX Factory - Get pair info
factory = ProtocolContract(contract, "unknown", "factory")
pairs_length = factory.call_protocol_method("allPairsLength")
print(f"Total pairs: {{pairs_length}}")

# Get specific pair
# pair_addr = factory.call_protocol_method("getPair", [tokenA, tokenB])
"""

        elif role == "lending_pool":
            code += """
# Lending Pool - Supply and borrow
pool = ProtocolContract(contract, "unknown", "lending_pool")

# Get user account data
account = pool.get_user_account_data("0x...")
print(f"Health Factor: {{account['healthFactor'] / 10**18:.2f}}")

# Supply (need private key)
# pool.supply(asset, amount, on_behalf_of, private_key=key)

# Borrow (need private key)
# pool.borrow(asset, amount, interest_rate_mode=2, private_key=key)
"""

        elif role == "price_feed":
            code += """
# Oracle - Get price
oracle = ProtocolContract(contract, "chainlink", "price_feed")
price_data = oracle.get_price()
price = price_data["answer"] / (10 ** price_data["decimals"])
print(f"Price: ${{price:.2f}}")
"""

        elif role == "staking":
            code += """
# Staking - Stake and claim rewards
staking = ProtocolContract(contract, "unknown", "staking")

# Get earned rewards
rewards = staking.get_staking_rewards("0x...")
print(f"Rewards: {{rewards}}")

# Stake (need private key)
# staking.stake(amount, private_key=key)
"""

        else:
            code += """
# Generic contract call
result = contract.call("methodName", [param1, param2])
print(f"Result: {{result}}")

# With protocol awareness
smart = ProtocolContract(contract)
print(f"Protocol: {{smart.protocol_name}}")
print(f"Role: {{smart.role}}")
info = smart.get_contract_info()
print(f"Available methods: {{len(info.get('methods', []))}}")
"""

        code += """
client.close()
"""
        return code
