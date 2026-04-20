#!/usr/bin/env python3
"""
Universal Contract Classifier
Probes contracts on-chain to determine their type and available methods.
Works with ANY contract, not just registered protocols.
"""

import json
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

from ..core.contract import Contract
from ..core.chain import Chain
from .catalog import ProtocolType, ContractRole, ContractMethod, catalog


# Method signature hashes (first 4 bytes of keccak256)
METHOD_SELECTORS = {
    # ERC20
    "0x06fdde03": {"name": "name", "category": "erc20", "template": "erc20"},
    "0x95d89b41": {"name": "symbol", "category": "erc20", "template": "erc20"},
    "0x313ce567": {"name": "decimals", "category": "erc20", "template": "erc20"},
    "0x18160ddd": {"name": "totalSupply", "category": "erc20", "template": "erc20"},
    "0x70a08231": {"name": "balanceOf", "category": "erc20", "template": "erc20"},
    "0xa9059cbb": {"name": "transfer", "category": "erc20", "template": "erc20"},
    "0xdd62ed3e": {"name": "allowance", "category": "erc20", "template": "erc20"},
    "0x095ea7b3": {"name": "approve", "category": "erc20", "template": "erc20"},
    "0x23b872dd": {"name": "transferFrom", "category": "erc20", "template": "erc20"},
    # Uniswap V2 Router
    "0xf305d719": {
        "name": "addLiquidityETH",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0xe8e33700": {
        "name": "addLiquidity",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0xbaa2abde": {
        "name": "removeLiquidity",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0x02751cec": {
        "name": "removeLiquidityETH",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0x38ed1739": {
        "name": "swapExactTokensForTokens",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0x8803dbee": {
        "name": "swapTokensForExactTokens",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0x7ff36ab5": {
        "name": "swapExactETHForTokens",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0x18cbafe5": {
        "name": "swapExactTokensForETH",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0xfb3bdb41": {
        "name": "swapETHForExactTokens",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0x4a25d94a": {
        "name": "swapTokensForExactETH",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0xd06ca61f": {
        "name": "getAmountsOut",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0x1f00ca74": {
        "name": "getAmountsIn",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0xc45a0155": {
        "name": "factory",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    "0xad5c4648": {
        "name": "WETH",
        "category": "dex_router_v2",
        "template": "uniswap_v2_router",
    },
    # Uniswap V2 Factory
    "0xe6a43905": {
        "name": "getPair",
        "category": "dex_factory_v2",
        "template": "uniswap_v2_factory",
    },
    "0x574f2ba3": {
        "name": "allPairsLength",
        "category": "dex_factory_v2",
        "template": "uniswap_v2_factory",
    },
    "0x6801cc30": {
        "name": "createPair",
        "category": "dex_factory_v2",
        "template": "uniswap_v2_factory",
    },
    "0x1e3dd18b": {
        "name": "allPairs",
        "category": "dex_factory_v2",
        "template": "uniswap_v2_factory",
    },
    # Uniswap V2 Pair
    "0x0dfe1681": {
        "name": "token0",
        "category": "dex_pair",
        "template": "uniswap_v2_pair",
    },
    "0xd21220a7": {
        "name": "token1",
        "category": "dex_pair",
        "template": "uniswap_v2_pair",
    },
    "0x0902f1ac": {
        "name": "getReserves",
        "category": "dex_pair",
        "template": "uniswap_v2_pair",
    },
    "0x485cc955": {
        "name": "initialize",
        "category": "dex_pair",
        "template": "uniswap_v2_pair",
    },
    "0xfff6cae9": {
        "name": "sync",
        "category": "dex_pair",
        "template": "uniswap_v2_pair",
    },
    "0xbc25cf77": {
        "name": "skim",
        "category": "dex_pair",
        "template": "uniswap_v2_pair",
    },
    # Uniswap V3
    "0x414bf389": {
        "name": "exactInputSingle",
        "category": "dex_router_v3",
        "template": "uniswap_v3_router",
    },
    "0xc04b8d59": {
        "name": "exactInput",
        "category": "dex_router_v3",
        "template": "uniswap_v3_router",
    },
    "0xdb3e2198": {
        "name": "exactOutputSingle",
        "category": "dex_router_v3",
        "template": "uniswap_v3_router",
    },
    "0xf28c0498": {
        "name": "exactOutput",
        "category": "dex_router_v3",
        "template": "uniswap_v3_router",
    },
    "0x1698ee82": {
        "name": "exactInputSingle (V3 SwapRouter02)",
        "category": "dex_router_v3",
        "template": "uniswap_v3_router",
    },
    # Curve
    "0x3df02126": {
        "name": "exchange",
        "category": "dex_curve",
        "template": "curve_router",
    },
    "0xa6417ed6": {
        "name": "exchange_underlying",
        "category": "dex_curve",
        "template": "curve_router",
    },
    "0x5e0d443f": {
        "name": "get_dy",
        "category": "dex_curve",
        "template": "curve_router",
    },
    "0x07211ef7": {
        "name": "get_dy_underlying",
        "category": "dex_curve",
        "template": "curve_router",
    },
    "0x4903b0d1": {
        "name": "balances",
        "category": "dex_curve",
        "template": "curve_router",
    },
    "0xf446c1d0": {"name": "A", "category": "dex_curve", "template": "curve_router"},
    "0xddca3f43": {"name": "fee", "category": "dex_curve", "template": "curve_router"},
    "0x87d2f4f8": {
        "name": "add_liquidity",
        "category": "dex_curve",
        "template": "curve_router",
    },
    # Aave V3 Lending
    "0x617ba037": {"name": "supply", "category": "lending", "template": "aave_v3_pool"},
    "0x69328dec": {
        "name": "withdraw",
        "category": "lending",
        "template": "aave_v3_pool",
    },
    "0xe43e10c0": {"name": "borrow", "category": "lending", "template": "aave_v3_pool"},
    "0x573ade81": {"name": "repay", "category": "lending", "template": "aave_v3_pool"},
    "0xbf92857c": {
        "name": "getUserAccountData",
        "category": "lending",
        "template": "aave_v3_pool",
    },
    "0x35ea6a75": {
        "name": "getReserveData",
        "category": "lending",
        "template": "aave_v3_pool",
    },
    "0x5cffe9de": {
        "name": "flashLoan",
        "category": "lending",
        "template": "aave_v3_pool",
    },
    "0x26c16e7c": {
        "name": "flashLoanSimple",
        "category": "lending",
        "template": "aave_v3_pool",
    },
    # Compound-style Lending
    "0x1249c58b": {
        "name": "mint",
        "category": "lending_ctoken",
        "template": "aave_v3_pool",
    },
    "0xdb006a75": {
        "name": "redeem",
        "category": "lending_ctoken",
        "template": "aave_v3_pool",
    },
    "0x852a12e3": {
        "name": "redeemUnderlying",
        "category": "lending_ctoken",
        "template": "aave_v3_pool",
    },
    "0xc5ebeaec": {
        "name": "borrow",
        "category": "lending_ctoken",
        "template": "aave_v3_pool",
    },
    "0x0e752702": {
        "name": "repayBorrow",
        "category": "lending_ctoken",
        "template": "aave_v3_pool",
    },
    # Staking
    "0xa694fc3a": {
        "name": "stake",
        "category": "staking",
        "template": "staking_generic",
    },
    "0x2e1a7d4d": {
        "name": "withdraw",
        "category": "staking",
        "template": "staking_generic",
    },
    "0x3d18b912": {
        "name": "getReward",
        "category": "staking",
        "template": "staking_generic",
    },
    "0x008cc211": {
        "name": "earned",
        "category": "staking",
        "template": "staking_generic",
    },
    "0x7050ccd9": {
        "name": "exit",
        "category": "staking",
        "template": "staking_generic",
    },
    # Oracle / Price Feed
    "0x50d25bcd": {
        "name": "latestAnswer",
        "category": "oracle",
        "template": "oracle_chainlink",
    },
    "0xfeaf968c": {
        "name": "latestRoundData",
        "category": "oracle",
        "template": "oracle_chainlink",
    },
    "0x9a6fc8f9": {
        "name": "getAnswer",
        "category": "oracle",
        "template": "oracle_chainlink",
    },
    "0x8205bf6a": {
        "name": "latestTimestamp",
        "category": "oracle",
        "template": "oracle_chainlink",
    },
    # Bridge
    "0x0100d4a6": {
        "name": "bridge",
        "category": "bridge",
        "template": "bridge_generic",
    },
    "0x5f5b7a87": {"name": "claim", "category": "bridge", "template": "bridge_generic"},
    "0x4630a0d5": {
        "name": "sendMessage",
        "category": "bridge",
        "template": "bridge_generic",
    },
    "0x07e40452": {
        "name": "estimateFees",
        "category": "bridge",
        "template": "bridge_generic",
    },
    # Vault / Yield
    "0x6e553f65": {
        "name": "deposit",
        "category": "vault",
        "template": "staking_generic",
    },
    "0x2e17de78": {
        "name": "revoke",
        "category": "vault",
        "template": "staking_generic",
    },
    "0xba087652": {"name": "earn", "category": "vault", "template": "staking_generic"},
    # Governance
    "0x56781388": {"name": "castVote", "category": "governance", "template": "erc20"},
    "0x15373e3d": {"name": "propose", "category": "governance", "template": "erc20"},
    # Multicall
    "0x252dba42": {"name": "aggregate", "category": "multicall", "template": "erc20"},
    "0x5a3b7e49": {
        "name": "tryAggregate",
        "category": "multicall",
        "template": "erc20",
    },
    # ERC721 (NFT)
    "0x70a08231": {"name": "balanceOf", "category": "erc721", "template": "erc20"},
    "0x6352211e": {"name": "ownerOf", "category": "erc721", "template": "erc20"},
    "0x42842e0e": {
        "name": "safeTransferFrom",
        "category": "erc721",
        "template": "erc20",
    },
    "0xa22cb465": {
        "name": "setApprovalForAll",
        "category": "erc721",
        "template": "erc20",
    },
    "0x081812fc": {"name": "getApproved", "category": "erc721", "template": "erc20"},
    # ERC1155
    "0x00fdd58e": {
        "name": "balanceOf (1155)",
        "category": "erc1155",
        "template": "erc20",
    },
    "0x4e1273f4": {
        "name": "balanceOfBatch",
        "category": "erc1155",
        "template": "erc20",
    },
    "0xf242432a": {
        "name": "safeTransferFrom (1155)",
        "category": "erc1155",
        "template": "erc20",
    },
    # Proxy patterns
    "0x5c60da1b": {"name": "implementation", "category": "proxy", "template": "erc20"},
    "0x360894a1": {
        "name": "implementation (EIP1967)",
        "category": "proxy",
        "template": "erc20",
    },
    # Swap aggregators
    "0x12aa3caf": {
        "name": "swap",
        "category": "aggregator",
        "template": "uniswap_v2_router",
    },
    "0x90411a32": {
        "name": "swap (0x)",
        "category": "aggregator",
        "template": "uniswap_v2_router",
    },
    "0xd9627aa4": {
        "name": "sellToUniswap",
        "category": "aggregator",
        "template": "uniswap_v2_router",
    },
    # Liquidity manager
    "0x0d8d4a83": {
        "name": "addLiquidity (Vault)",
        "category": "liquidity_manager",
        "template": "uniswap_v2_router",
    },
    "0x0f5a8e05": {
        "name": "removeLiquidity (Vault)",
        "category": "liquidity_manager",
        "template": "uniswap_v2_router",
    },
    # Wrapped native tokens
    "0x2e1a7d4d": {
        "name": "withdraw",
        "category": "wrapped_native",
        "template": "erc20",
    },
    "0xd0e30db0": {
        "name": "deposit",
        "category": "wrapped_native",
        "template": "erc20",
    },
}


@dataclass
class ContractClassification:
    """Result of contract classification."""

    address: str
    chain: str
    detected_categories: List[str] = field(default_factory=list)
    matched_methods: List[Dict[str, Any]] = field(default_factory=list)
    suggested_template: Optional[str] = None
    suggested_role: Optional[str] = None
    suggested_protocol_type: Optional[ProtocolType] = None
    confidence: float = 0.0
    erc20_info: Optional[Dict[str, Any]] = None
    bytecode_size: int = 0
    is_proxy: bool = False
    implementation_address: Optional[str] = None
    raw_bytecode: str = ""


# Category -> (role, protocol_type) mapping
CATEGORY_MAPPING = {
    "erc20": (ContractRole.TOKEN, ProtocolType.OTHER),
    "dex_router_v2": (ContractRole.ROUTER, ProtocolType.DEX),
    "dex_router_v3": (ContractRole.ROUTER, ProtocolType.DEX),
    "dex_factory_v2": (ContractRole.FACTORY, ProtocolType.DEX),
    "dex_pair": (ContractRole.PAIR, ProtocolType.DEX),
    "dex_curve": (ContractRole.ROUTER, ProtocolType.DEX),
    "lending": (ContractRole.LENDING_POOL, ProtocolType.LENDING),
    "lending_ctoken": (ContractRole.LENDING_POOL, ProtocolType.LENDING),
    "staking": (ContractRole.STAKING, ProtocolType.YIELD),
    "oracle": (ContractRole.PRICE_FEED, ProtocolType.ORACLE),
    "bridge": (ContractRole.BRIDGE_IN, ProtocolType.BRIDGE),
    "vault": (ContractRole.VAULT, ProtocolType.YIELD),
    "governance": (ContractRole.GOVERNOR, ProtocolType.GOVERNANCE),
    "multicall": (ContractRole.OTHER, ProtocolType.OTHER),
    "erc721": (ContractRole.OTHER, ProtocolType.NFT),
    "erc1155": (ContractRole.OTHER, ProtocolType.NFT),
    "proxy": (ContractRole.OTHER, ProtocolType.OTHER),
    "aggregator": (ContractRole.AGGREGATOR, ProtocolType.AGGREGATOR),
    "liquidity_manager": (ContractRole.OTHER, ProtocolType.LIQUIDITY_MANAGER),
    "wrapped_native": (ContractRole.TOKEN, ProtocolType.OTHER),
}


class ContractClassifier:
    """
    Universal contract classifier.
    Probes contracts on-chain to determine type and capabilities.
    Works with ANY contract.
    """

    def __init__(self, rpc_provider=None):
        """Initialize classifier."""
        self.rpc_provider = rpc_provider

    def _get_selector(self, data: str) -> str:
        """Extract method selector from calldata."""
        if data and len(data) >= 10:
            return data[:10].lower()
        return ""

    def probe_bytecode(self, chain: Chain, address: str) -> Dict[str, Any]:
        """
        Probe contract bytecode to detect method selectors.

        Returns dict with detected selectors and their meanings.
        """
        result = {
            "has_code": False,
            "bytecode_size": 0,
            "detected_selectors": [],
            "categories": set(),
            "matched_methods": [],
            "is_proxy": False,
        }

        if not self.rpc_provider:
            return result

        try:
            # Get bytecode
            code = self.rpc_provider.get_code(chain.name, address)
            if not code or code == "0x":
                return result

            result["has_code"] = True
            result["bytecode_size"] = (len(code) - 2) // 2  # Remove 0x prefix

            # Check for proxy patterns
            # EIP-1967 implementation slot
            impl_slot = (
                "0x360894a1aab8f78a0e9fdde4c0e5c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c"
            )
            if "360894a1" in code.lower():
                result["is_proxy"] = True

            # Scan bytecode for known method selectors
            code_lower = code.lower()
            for selector, info in METHOD_SELECTORS.items():
                # Look for selector in bytecode (as PUSH4 instruction pattern)
                selector_hex = selector[2:]  # Remove 0x
                if selector_hex in code_lower:
                    result["detected_selectors"].append(
                        {
                            "selector": selector,
                            "name": info["name"],
                            "category": info["category"],
                        }
                    )
                    result["categories"].add(info["category"])
                    result["matched_methods"].append(info)

        except Exception as e:
            print(f"Error probing bytecode: {e}")

        return result

    def classify_contract(self, chain: Chain, address: str) -> ContractClassification:
        """
        Classify a contract by probing its bytecode and calling common methods.

        Args:
            chain: Chain object
            address: Contract address

        Returns:
            ContractClassification with detected type and methods
        """
        classification = ContractClassification(address=address, chain=chain.name)

        # Step 1: Probe bytecode
        if self.rpc_provider:
            probe = self.probe_bytecode(chain, address)
            classification.bytecode_size = probe["bytecode_size"]
            classification.is_proxy = probe["is_proxy"]
            classification.matched_methods = probe["matched_methods"]

            for cat in probe["categories"]:
                classification.detected_categories.append(cat)

        # Step 2: Try calling ERC20 methods
        erc20_info = self._try_erc20_methods(chain, address)
        if erc20_info:
            classification.erc20_info = erc20_info
            if "erc20" not in classification.detected_categories:
                classification.detected_categories.append("erc20")

        # Step 3: Determine best classification
        classification = self._determine_classification(classification)

        return classification

    def _try_erc20_methods(
        self, chain: Chain, address: str
    ) -> Optional[Dict[str, Any]]:
        """Try calling ERC20 methods to get token info."""
        if not self.rpc_provider:
            return None

        info = {}
        erc20_methods = ["name", "symbol", "decimals", "totalSupply"]

        for method in erc20_methods:
            try:
                result = self.rpc_provider.call_contract(
                    chain.name, address, method, []
                )
                if result is not None:
                    info[method] = result
            except Exception:
                pass

        return info if info else None

    def _determine_classification(
        self, classification: ContractClassification
    ) -> ContractClassification:
        """Determine best classification from detected categories."""
        if not classification.detected_categories:
            classification.suggested_template = "erc20"
            classification.suggested_role = "token"
            classification.suggested_protocol_type = ProtocolType.OTHER
            classification.confidence = 0.1
            return classification

        # Priority order for classification
        priority = [
            "dex_router_v2",
            "dex_router_v3",
            "dex_factory_v2",
            "dex_pair",
            "dex_curve",
            "lending",
            "lending_ctoken",
            "bridge",
            "oracle",
            "staking",
            "vault",
            "aggregator",
            "governance",
            "erc721",
            "erc1155",
            "wrapped_native",
            "erc20",
            "proxy",
            "multicall",
        ]

        # Find highest priority category
        best_category = None
        for cat in priority:
            if cat in classification.detected_categories:
                best_category = cat
                break

        if not best_category:
            best_category = classification.detected_categories[0]

        # Map to role and protocol type
        if best_category in CATEGORY_MAPPING:
            role, proto_type = CATEGORY_MAPPING[best_category]
            classification.suggested_role = role.value
            classification.suggested_protocol_type = proto_type

        # Get template
        for method in classification.matched_methods:
            if method.get("category") == best_category:
                classification.suggested_template = method.get("template")
                break

        if not classification.suggested_template:
            classification.suggested_template = "erc20"

        # Calculate confidence
        classification.confidence = self._calculate_confidence(classification)

        return classification

    def _calculate_confidence(self, classification: ContractClassification) -> float:
        """Calculate confidence score for classification."""
        score = 0.0

        # More detected categories = higher confidence
        score += min(len(classification.detected_categories) * 0.15, 0.45)

        # More matched methods = higher confidence
        score += min(len(classification.matched_methods) * 0.03, 0.30)

        # Has ERC20 info = bonus
        if classification.erc20_info:
            score += 0.15

        # Non-trivial bytecode = bonus
        if classification.bytecode_size > 100:
            score += 0.10

        return min(score, 1.0)

    def classify_batch(
        self, chain: Chain, addresses: List[str]
    ) -> List[ContractClassification]:
        """
        Classify multiple contracts in batch.

        Args:
            chain: Chain object
            addresses: List of contract addresses

        Returns:
            List of classifications
        """
        return [self.classify_contract(chain, addr) for addr in addresses]

    def get_interaction_methods(
        self, classification: ContractClassification
    ) -> List[Dict[str, Any]]:
        """
        Get recommended interaction methods based on classification.

        Returns:
            List of method dicts with name, signature, category, description
        """
        methods = []

        # Get methods from template
        if classification.suggested_template:
            template = catalog.get_template(classification.suggested_template)
            if template:
                for method in template.methods:
                    methods.append(
                        {
                            "name": method.name,
                            "signature": method.signature,
                            "category": method.category,
                            "description": method.description,
                            "state_mutability": method.state_mutability,
                            "gas_estimate": method.gas_estimate,
                            "inputs": method.inputs,
                            "outputs": method.outputs,
                            "source": "template",
                        }
                    )

        # Add detected methods from bytecode
        seen = {m["name"] for m in methods}
        for matched in classification.matched_methods:
            if matched["name"] not in seen:
                methods.append(
                    {
                        "name": matched["name"],
                        "category": matched["category"],
                        "source": "bytecode_detection",
                    }
                )
                seen.add(matched["name"])

        return methods
