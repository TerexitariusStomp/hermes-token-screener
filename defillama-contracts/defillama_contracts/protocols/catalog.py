#!/usr/bin/env python3
"""
Protocol-specific contract interaction catalog.
Defines standard ABI patterns and methods for DEXes, bridges, lending, and other protocols.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum


class ProtocolType(Enum):
    """Type of DeFi protocol."""
    DEX = "dex"
    BRIDGE = "bridge"
    LENDING = "lending"
    YIELD = "yield"
    DERIVATIVES = "derivatives"
    STABLECOIN = "stablecoin"
    GOVERNANCE = "governance"
    AGGREGATOR = "aggregator"
    LIQUIDITY_MANAGER = "liquidity_manager"
    ORACLE = "oracle"
    INSURANCE = "insurance"
    NFT = "nft"
    PAYMENT = "payment"
    IDENTITY = "identity"
    OTHER = "other"


class ContractRole(Enum):
    """Role of a contract within a protocol."""
    ROUTER = "router"
    FACTORY = "factory"
    PAIR = "pair"
    TOKEN = "token"
    VAULT = "vault"
    CONTROLLER = "controller"
    ORACLE = "oracle"
    GOVERNOR = "governor"
    STAKING = "staking"
    REWARD = "reward"
    BRIDGE_IN = "bridge_in"
    BRIDGE_OUT = "bridge_out"
    LENDING_POOL = "lending_pool"
    COLLATERAL_MANAGER = "collateral_manager"
    PRICE_FEED = "price_feed"
    AGGREGATOR = "aggregator"
    OTHER = "other"


@dataclass
class ContractMethod:
    """Definition of a contract method."""
    name: str
    signature: str  # Full Solidity signature
    inputs: List[Dict[str, str]]  # [{"name": "token", "type": "address"}, ...]
    outputs: List[Dict[str, str]]  # [{"type": "uint256"}, ...]
    state_mutability: str  # "view", "pure", "nonpayable", "payable"
    description: str = ""
    category: str = ""  # "read", "write", "query", "admin"
    gas_estimate: Optional[int] = None
    example_params: Optional[List[Any]] = None
    example_result: Optional[Any] = None


@dataclass
class ProtocolTemplate:
    """Template defining standard methods for a protocol type."""
    protocol_type: ProtocolType
    contract_role: ContractRole
    methods: List[ContractMethod] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    standard_interfaces: List[str] = field(default_factory=list)  # ERC20, ERC721, etc.
    notes: str = ""


class ProtocolCatalog:
    """Catalog of protocol-specific contract patterns."""
    
    def __init__(self):
        self.templates: Dict[str, ProtocolTemplate] = {}
        self._initialize_standard_templates()
    
    def _initialize_standard_templates(self):
        """Initialize standard protocol templates."""
        
        # ERC20 Token Standard
        self.templates["erc20"] = ProtocolTemplate(
            protocol_type=ProtocolType.OTHER,
            contract_role=ContractRole.TOKEN,
            standard_interfaces=["ERC20"],
            methods=[
                ContractMethod(
                    name="name",
                    signature="name()",
                    inputs=[],
                    outputs=[{"type": "string"}],
                    state_mutability="view",
                    description="Get token name",
                    category="read"
                ),
                ContractMethod(
                    name="symbol",
                    signature="symbol()",
                    inputs=[],
                    outputs=[{"type": "string"}],
                    state_mutability="view",
                    description="Get token symbol",
                    category="read"
                ),
                ContractMethod(
                    name="decimals",
                    signature="decimals()",
                    inputs=[],
                    outputs=[{"type": "uint8"}],
                    state_mutability="view",
                    description="Get token decimals",
                    category="read"
                ),
                ContractMethod(
                    name="totalSupply",
                    signature="totalSupply()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get total supply",
                    category="read"
                ),
                ContractMethod(
                    name="balanceOf",
                    signature="balanceOf(address)",
                    inputs=[{"name": "account", "type": "address"}],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get balance of account",
                    category="read"
                ),
                ContractMethod(
                    name="transfer",
                    signature="transfer(address,uint256)",
                    inputs=[
                        {"name": "to", "type": "address"},
                        {"name": "amount", "type": "uint256"}
                    ],
                    outputs=[{"type": "bool"}],
                    state_mutability="nonpayable",
                    description="Transfer tokens",
                    category="write",
                    gas_estimate=65000
                ),
                ContractMethod(
                    name="allowance",
                    signature="allowance(address,address)",
                    inputs=[
                        {"name": "owner", "type": "address"},
                        {"name": "spender", "type": "address"}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get allowance",
                    category="read"
                ),
                ContractMethod(
                    name="approve",
                    signature="approve(address,uint256)",
                    inputs=[
                        {"name": "spender", "type": "address"},
                        {"name": "amount", "type": "uint256"}
                    ],
                    outputs=[{"type": "bool"}],
                    state_mutability="nonpayable",
                    description="Approve spender",
                    category="write",
                    gas_estimate=46000
                ),
                ContractMethod(
                    name="transferFrom",
                    signature="transferFrom(address,address,uint256)",
                    inputs=[
                        {"name": "from", "type": "address"},
                        {"name": "to", "type": "address"},
                        {"name": "amount", "type": "uint256"}
                    ],
                    outputs=[{"type": "bool"}],
                    state_mutability="nonpayable",
                    description="Transfer from",
                    category="write",
                    gas_estimate=65000
                ),
            ],
            events=[
                {
                    "name": "Transfer",
                    "inputs": [
                        {"name": "from", "type": "address", "indexed": True},
                        {"name": "to", "type": "address", "indexed": True},
                        {"name": "value", "type": "uint256", "indexed": False}
                    ]
                },
                {
                    "name": "Approval",
                    "inputs": [
                        {"name": "owner", "type": "address", "indexed": True},
                        {"name": "spender", "type": "address", "indexed": True},
                        {"name": "value", "type": "uint256", "indexed": False}
                    ]
                }
            ]
        )
        
        # Uniswap V2 Router
        self.templates["uniswap_v2_router"] = ProtocolTemplate(
            protocol_type=ProtocolType.DEX,
            contract_role=ContractRole.ROUTER,
            standard_interfaces=["IUniswapV2Router02"],
            methods=[
                ContractMethod(
                    name="factory",
                    signature="factory()",
                    inputs=[],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get factory address",
                    category="read"
                ),
                ContractMethod(
                    name="WETH",
                    signature="WETH()",
                    inputs=[],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get WETH address",
                    category="read"
                ),
                ContractMethod(
                    name="addLiquidity",
                    signature="addLiquidity(address,address,uint256,uint256,uint256,uint256,address,uint256)",
                    inputs=[
                        {"name": "tokenA", "type": "address"},
                        {"name": "tokenB", "type": "address"},
                        {"name": "amountADesired", "type": "uint256"},
                        {"name": "amountBDesired", "type": "uint256"},
                        {"name": "amountAMin", "type": "uint256"},
                        {"name": "amountBMin", "type": "uint256"},
                        {"name": "to", "type": "address"},
                        {"name": "deadline", "type": "uint256"}
                    ],
                    outputs=[
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint256"}
                    ],
                    state_mutability="nonpayable",
                    description="Add liquidity to pair",
                    category="write",
                    gas_estimate=200000
                ),
                ContractMethod(
                    name="removeLiquidity",
                    signature="removeLiquidity(address,address,uint256,uint256,uint256,address,uint256)",
                    inputs=[
                        {"name": "tokenA", "type": "address"},
                        {"name": "tokenB", "type": "address"},
                        {"name": "liquidity", "type": "uint256"},
                        {"name": "amountAMin", "type": "uint256"},
                        {"name": "amountBMin", "type": "uint256"},
                        {"name": "to", "type": "address"},
                        {"name": "deadline", "type": "uint256"}
                    ],
                    outputs=[
                        {"type": "uint256"},
                        {"type": "uint256"}
                    ],
                    state_mutability="nonpayable",
                    description="Remove liquidity from pair",
                    category="write",
                    gas_estimate=200000
                ),
                ContractMethod(
                    name="swapExactTokensForTokens",
                    signature="swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
                    inputs=[
                        {"name": "amountIn", "type": "uint256"},
                        {"name": "amountOutMin", "type": "uint256"},
                        {"name": "path", "type": "address[]"},
                        {"name": "to", "type": "address"},
                        {"name": "deadline", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256[]"}],
                    state_mutability="nonpayable",
                    description="Swap exact tokens for tokens",
                    category="write",
                    gas_estimate=150000
                ),
                ContractMethod(
                    name="swapTokensForExactTokens",
                    signature="swapTokensForExactTokens(uint256,uint256,address[],address,uint256)",
                    inputs=[
                        {"name": "amountOut", "type": "uint256"},
                        {"name": "amountInMax", "type": "uint256"},
                        {"name": "path", "type": "address[]"},
                        {"name": "to", "type": "address"},
                        {"name": "deadline", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256[]"}],
                    state_mutability="nonpayable",
                    description="Swap tokens for exact tokens",
                    category="write",
                    gas_estimate=150000
                ),
                ContractMethod(
                    name="swapExactETHForTokens",
                    signature="swapExactETHForTokens(uint256,address[],address,uint256)",
                    inputs=[
                        {"name": "amountOutMin", "type": "uint256"},
                        {"name": "path", "type": "address[]"},
                        {"name": "to", "type": "address"},
                        {"name": "deadline", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256[]"}],
                    state_mutability="payable",
                    description="Swap exact ETH for tokens",
                    category="write",
                    gas_estimate=150000
                ),
                ContractMethod(
                    name="swapTokensForExactETH",
                    signature="swapTokensForExactETH(uint256,uint256,address[],address,uint256)",
                    inputs=[
                        {"name": "amountOut", "type": "uint256"},
                        {"name": "amountInMax", "type": "uint256"},
                        {"name": "path", "type": "address[]"},
                        {"name": "to", "type": "address"},
                        {"name": "deadline", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256[]"}],
                    state_mutability="nonpayable",
                    description="Swap tokens for exact ETH",
                    category="write",
                    gas_estimate=150000
                ),
                ContractMethod(
                    name="getAmountsOut",
                    signature="getAmountsOut(uint256,address[])",
                    inputs=[
                        {"name": "amountIn", "type": "uint256"},
                        {"name": "path", "type": "address[]"}
                    ],
                    outputs=[{"type": "uint256[]"}],
                    state_mutability="view",
                    description="Get output amounts for input",
                    category="read"
                ),
                ContractMethod(
                    name="getAmountsIn",
                    signature="getAmountsIn(uint256,address[])",
                    inputs=[
                        {"name": "amountOut", "type": "uint256"},
                        {"name": "path", "type": "address[]"}
                    ],
                    outputs=[{"type": "uint256[]"}],
                    state_mutability="view",
                    description="Get input amounts for output",
                    category="read"
                ),
                ContractMethod(
                    name="quote",
                    signature="quote(uint256,uint256,uint256)",
                    inputs=[
                        {"name": "amountA", "type": "uint256"},
                        {"name": "reserveA", "type": "uint256"},
                        {"name": "reserveB", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="pure",
                    description="Quote price based on reserves",
                    category="read"
                ),
            ]
        )
        
        # Uniswap V2 Factory
        self.templates["uniswap_v2_factory"] = ProtocolTemplate(
            protocol_type=ProtocolType.DEX,
            contract_role=ContractRole.FACTORY,
            standard_interfaces=["IUniswapV2Factory"],
            methods=[
                ContractMethod(
                    name="feeTo",
                    signature="feeTo()",
                    inputs=[],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get fee recipient",
                    category="read"
                ),
                ContractMethod(
                    name="feeToSetter",
                    signature="feeToSetter()",
                    inputs=[],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get fee setter",
                    category="read"
                ),
                ContractMethod(
                    name="getPair",
                    signature="getPair(address,address)",
                    inputs=[
                        {"name": "tokenA", "type": "address"},
                        {"name": "tokenB", "type": "address"}
                    ],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get pair address",
                    category="read"
                ),
                ContractMethod(
                    name="allPairsLength",
                    signature="allPairsLength()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get total pairs count",
                    category="read"
                ),
                ContractMethod(
                    name="createPair",
                    signature="createPair(address,address)",
                    inputs=[
                        {"name": "tokenA", "type": "address"},
                        {"name": "tokenB", "type": "address"}
                    ],
                    outputs=[{"type": "address"}],
                    state_mutability="nonpayable",
                    description="Create new pair",
                    category="write",
                    gas_estimate=3500000
                ),
                ContractMethod(
                    name="allPairs",
                    signature="allPairs(uint256)",
                    inputs=[{"name": "index", "type": "uint256"}],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get pair by index",
                    category="read"
                ),
            ]
        )
        
        # Uniswap V2 Pair
        self.templates["uniswap_v2_pair"] = ProtocolTemplate(
            protocol_type=ProtocolType.DEX,
            contract_role=ContractRole.PAIR,
            standard_interfaces=["IUniswapV2Pair", "ERC20"],
            methods=[
                ContractMethod(
                    name="token0",
                    signature="token0()",
                    inputs=[],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get token0 address",
                    category="read"
                ),
                ContractMethod(
                    name="token1",
                    signature="token1()",
                    inputs=[],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get token1 address",
                    category="read"
                ),
                ContractMethod(
                    name="getReserves",
                    signature="getReserves()",
                    inputs=[],
                    outputs=[
                        {"type": "uint112"},
                        {"type": "uint112"},
                        {"type": "uint32"}
                    ],
                    state_mutability="view",
                    description="Get pair reserves",
                    category="read"
                ),
                ContractMethod(
                    name="price0CumulativeLast",
                    signature="price0CumulativeLast()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get cumulative price0",
                    category="read"
                ),
                ContractMethod(
                    name="price1CumulativeLast",
                    signature="price1CumulativeLast()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get cumulative price1",
                    category="read"
                ),
                ContractMethod(
                    name="kLast",
                    signature="kLast()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get reserve product",
                    category="read"
                ),
                ContractMethod(
                    name="swap",
                    signature="swap(uint256,uint256,address,bytes)",
                    inputs=[
                        {"name": "amount0Out", "type": "uint256"},
                        {"name": "amount1Out", "type": "uint256"},
                        {"name": "to", "type": "address"},
                        {"name": "data", "type": "bytes"}
                    ],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Execute swap",
                    category="write",
                    gas_estimate=120000
                ),
                ContractMethod(
                    name="sync",
                    signature="sync()",
                    inputs=[],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Sync reserves",
                    category="write",
                    gas_estimate=50000
                ),
                ContractMethod(
                    name="skim",
                    signature="skim(address)",
                    inputs=[{"name": "to", "type": "address"}],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Skim excess tokens",
                    category="write",
                    gas_estimate=50000
                ),
            ]
        )
        
        # Uniswap V3 Router
        self.templates["uniswap_v3_router"] = ProtocolTemplate(
            protocol_type=ProtocolType.DEX,
            contract_role=ContractRole.ROUTER,
            standard_interfaces=["ISwapRouter"],
            methods=[
                ContractMethod(
                    name="exactInputSingle",
                    signature="exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))",
                    inputs=[
                        {"name": "params", "type": "tuple", "components": [
                            {"name": "tokenIn", "type": "address"},
                            {"name": "tokenOut", "type": "address"},
                            {"name": "fee", "type": "uint24"},
                            {"name": "recipient", "type": "address"},
                            {"name": "deadline", "type": "uint256"},
                            {"name": "amountIn", "type": "uint256"},
                            {"name": "amountOutMinimum", "type": "uint256"},
                            {"name": "sqrtPriceLimitX96", "type": "uint160"}
                        ]}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="payable",
                    description="Exact input single swap",
                    category="write",
                    gas_estimate=150000
                ),
                ContractMethod(
                    name="exactInput",
                    signature="exactInput((bytes,address,uint256,uint256,uint256))",
                    inputs=[
                        {"name": "params", "type": "tuple", "components": [
                            {"name": "path", "type": "bytes"},
                            {"name": "recipient", "type": "address"},
                            {"name": "deadline", "type": "uint256"},
                            {"name": "amountIn", "type": "uint256"},
                            {"name": "amountOutMinimum", "type": "uint256"}
                        ]}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="payable",
                    description="Exact input multi-hop swap",
                    category="write",
                    gas_estimate=200000
                ),
                ContractMethod(
                    name="exactOutputSingle",
                    signature="exactOutputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))",
                    inputs=[
                        {"name": "params", "type": "tuple", "components": [
                            {"name": "tokenIn", "type": "address"},
                            {"name": "tokenOut", "type": "address"},
                            {"name": "fee", "type": "uint24"},
                            {"name": "recipient", "type": "address"},
                            {"name": "deadline", "type": "uint256"},
                            {"name": "amountOut", "type": "uint256"},
                            {"name": "amountInMaximum", "type": "uint256"},
                            {"name": "sqrtPriceLimitX96", "type": "uint160"}
                        ]}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="payable",
                    description="Exact output single swap",
                    category="write",
                    gas_estimate=150000
                ),
                ContractMethod(
                    name="exactOutput",
                    signature="exactOutput((bytes,address,uint256,uint256,uint256))",
                    inputs=[
                        {"name": "params", "type": "tuple", "components": [
                            {"name": "path", "type": "bytes"},
                            {"name": "recipient", "type": "address"},
                            {"name": "deadline", "type": "uint256"},
                            {"name": "amountOut", "type": "uint256"},
                            {"name": "amountInMaximum", "type": "uint256"}
                        ]}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="payable",
                    description="Exact output multi-hop swap",
                    category="write",
                    gas_estimate=200000
                ),
            ]
        )
        
        # Uniswap V3 Factory
        self.templates["uniswap_v3_factory"] = ProtocolTemplate(
            protocol_type=ProtocolType.DEX,
            contract_role=ContractRole.FACTORY,
            standard_interfaces=["IUniswapV3Factory"],
            methods=[
                ContractMethod(
                    name="owner",
                    signature="owner()",
                    inputs=[],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get factory owner",
                    category="read"
                ),
                ContractMethod(
                    name="feeAmountTickSpacing",
                    signature="feeAmountTickSpacing(uint24)",
                    inputs=[{"name": "fee", "type": "uint24"}],
                    outputs=[{"type": "int24"}],
                    state_mutability="view",
                    description="Get tick spacing for fee",
                    category="read"
                ),
                ContractMethod(
                    name="getPool",
                    signature="getPool(address,address,uint24)",
                    inputs=[
                        {"name": "tokenA", "type": "address"},
                        {"name": "tokenB", "type": "address"},
                        {"name": "fee", "type": "uint24"}
                    ],
                    outputs=[{"type": "address"}],
                    state_mutability="view",
                    description="Get pool address",
                    category="read"
                ),
                ContractMethod(
                    name="createPool",
                    signature="createPool(address,address,uint24)",
                    inputs=[
                        {"name": "tokenA", "type": "address"},
                        {"name": "tokenB", "type": "address"},
                        {"name": "fee", "type": "uint24"}
                    ],
                    outputs=[{"type": "address"}],
                    state_mutability="nonpayable",
                    description="Create new pool",
                    category="write",
                    gas_estimate=4500000
                ),
            ]
        )
        
        # Curve Router (StableSwap)
        self.templates["curve_router"] = ProtocolTemplate(
            protocol_type=ProtocolType.DEX,
            contract_role=ContractRole.ROUTER,
            standard_interfaces=["ICurveRouter"],
            methods=[
                ContractMethod(
                    name="exchange",
                    signature="exchange(int128,int128,uint256,uint256)",
                    inputs=[
                        {"name": "i", "type": "int128"},
                        {"name": "j", "type": "int128"},
                        {"name": "dx", "type": "uint256"},
                        {"name": "min_dy", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="nonpayable",
                    description="Exchange tokens",
                    category="write",
                    gas_estimate=300000
                ),
                ContractMethod(
                    name="exchange_underlying",
                    signature="exchange_underlying(int128,int128,uint256,uint256)",
                    inputs=[
                        {"name": "i", "type": "int128"},
                        {"name": "j", "type": "int128"},
                        {"name": "dx", "type": "uint256"},
                        {"name": "min_dy", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="nonpayable",
                    description="Exchange underlying tokens",
                    category="write",
                    gas_estimate=300000
                ),
                ContractMethod(
                    name="get_dy",
                    signature="get_dy(int128,int128,uint256)",
                    inputs=[
                        {"name": "i", "type": "int128"},
                        {"name": "j", "type": "int128"},
                        {"name": "dx", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get expected output",
                    category="read"
                ),
                ContractMethod(
                    name="get_dy_underlying",
                    signature="get_dy_underlying(int128,int128,uint256)",
                    inputs=[
                        {"name": "i", "type": "int128"},
                        {"name": "j", "type": "int128"},
                        {"name": "dx", "type": "uint256"}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get expected underlying output",
                    category="read"
                ),
                ContractMethod(
                    name="balances",
                    signature="balances(uint256)",
                    inputs=[{"name": "i", "type": "uint256"}],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get pool balance",
                    category="read"
                ),
                ContractMethod(
                    name="A",
                    signature="A()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get amplification coefficient",
                    category="read"
                ),
                ContractMethod(
                    name="fee",
                    signature="fee()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get pool fee",
                    category="read"
                ),
            ]
        )
        
        # Aave V3 Lending Pool
        self.templates["aave_v3_pool"] = ProtocolTemplate(
            protocol_type=ProtocolType.LENDING,
            contract_role=ContractRole.LENDING_POOL,
            standard_interfaces=["IPool"],
            methods=[
                ContractMethod(
                    name="supply",
                    signature="supply(address,uint256,address,uint16)",
                    inputs=[
                        {"name": "asset", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                        {"name": "onBehalfOf", "type": "address"},
                        {"name": "referralCode", "type": "uint16"}
                    ],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Supply asset to pool",
                    category="write",
                    gas_estimate=300000
                ),
                ContractMethod(
                    name="withdraw",
                    signature="withdraw(address,uint256,address)",
                    inputs=[
                        {"name": "asset", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                        {"name": "to", "type": "address"}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="nonpayable",
                    description="Withdraw asset from pool",
                    category="write",
                    gas_estimate=300000
                ),
                ContractMethod(
                    name="borrow",
                    signature="borrow(address,uint256,uint256,uint16,address)",
                    inputs=[
                        {"name": "asset", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                        {"name": "interestRateMode", "type": "uint256"},
                        {"name": "referralCode", "type": "uint16"},
                        {"name": "onBehalfOf", "type": "address"}
                    ],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Borrow asset from pool",
                    category="write",
                    gas_estimate=400000
                ),
                ContractMethod(
                    name="repay",
                    signature="repay(address,uint256,uint256,address)",
                    inputs=[
                        {"name": "asset", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                        {"name": "rateMode", "type": "uint256"},
                        {"name": "onBehalfOf", "type": "address"}
                    ],
                    outputs=[{"type": "uint256"}],
                    state_mutability="nonpayable",
                    description="Repay borrowed asset",
                    category="write",
                    gas_estimate=300000
                ),
                ContractMethod(
                    name="getUserAccountData",
                    signature="getUserAccountData(address)",
                    inputs=[{"name": "user", "type": "address"}],
                    outputs=[
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint256"}
                    ],
                    state_mutability="view",
                    description="Get user account data (collateral, debt, health factor)",
                    category="read"
                ),
                ContractMethod(
                    name="getReserveData",
                    signature="getReserveData(address)",
                    inputs=[{"name": "asset", "type": "address"}],
                    outputs=[
                        {"type": "tuple", "components": [
                            {"name": "configuration", "type": "uint256"},
                            {"name": "liquidityIndex", "type": "uint128"},
                            {"name": "currentLiquidityRate", "type": "uint128"},
                            {"name": "variableBorrowIndex", "type": "uint128"},
                            {"name": "currentVariableBorrowRate", "type": "uint128"},
                            {"name": "currentStableBorrowRate", "type": "uint128"},
                            {"name": "lastUpdateTimestamp", "type": "uint40"},
                            {"name": "id", "type": "uint16"},
                            {"name": "aTokenAddress", "type": "address"},
                            {"name": "stableDebtTokenAddress", "type": "address"},
                            {"name": "variableDebtTokenAddress", "type": "address"},
                            {"name": "interestRateStrategyAddress", "type": "address"},
                            {"name": "accruedToTreasury", "type": "uint128"},
                            {"name": "unbacked", "type": "uint128"},
                            {"name": "isolationModeTotalDebt", "type": "uint128"}
                        ]}
                    ],
                    state_mutability="view",
                    description="Get reserve data",
                    category="read"
                ),
                ContractMethod(
                    name="getReserveConfigurationData",
                    signature="getReserveConfigurationData(address)",
                    inputs=[{"name": "asset", "type": "address"}],
                    outputs=[
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "bool"},
                        {"type": "bool"},
                        {"type": "bool"},
                        {"type": "bool"}
                    ],
                    state_mutability="view",
                    description="Get reserve configuration",
                    category="read"
                ),
                ContractMethod(
                    name="flashLoan",
                    signature="flashLoan(address,address[],uint256[],uint256[],address,bytes,uint16)",
                    inputs=[
                        {"name": "receiverAddress", "type": "address"},
                        {"name": "assets", "type": "address[]"},
                        {"name": "amounts", "type": "uint256[]"},
                        {"name": "interestRateModes", "type": "uint256[]"},
                        {"name": "onBehalfOf", "type": "address"},
                        {"name": "params", "type": "bytes"},
                        {"name": "referralCode", "type": "uint16"}
                    ],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Execute flash loan",
                    category="write",
                    gas_estimate=1000000
                ),
            ]
        )
        
        # Bridge Contract (Generic)
        self.templates["bridge_generic"] = ProtocolTemplate(
            protocol_type=ProtocolType.BRIDGE,
            contract_role=ContractRole.BRIDGE_IN,
            standard_interfaces=["IBridge"],
            methods=[
                ContractMethod(
                    name="bridge",
                    signature="bridge(address,uint256,uint256,address)",
                    inputs=[
                        {"name": "token", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                        {"name": "destChainId", "type": "uint256"},
                        {"name": "recipient", "type": "address"}
                    ],
                    outputs=[],
                    state_mutability="payable",
                    description="Bridge tokens to another chain",
                    category="write",
                    gas_estimate=200000
                ),
                ContractMethod(
                    name="claim",
                    signature="claim(bytes32)",
                    inputs=[{"name": "messageId", "type": "bytes32"}],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Claim bridged tokens",
                    category="write",
                    gas_estimate=200000
                ),
                ContractMethod(
                    name="getMessageStatus",
                    signature="getMessageStatus(bytes32)",
                    inputs=[{"name": "messageId", "type": "bytes32"}],
                    outputs=[{"type": "uint8"}],
                    state_mutability="view",
                    description="Get message status (0=pending, 1=delivered, 2=failed)",
                    category="read"
                ),
                ContractMethod(
                    name="estimateFees",
                    signature="estimateFees(address,uint256,uint256,bool,bytes)",
                    inputs=[
                        {"name": "token", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                        {"name": "destChainId", "type": "uint256"},
                        {"name": "payInLzToken", "type": "bool"},
                        {"name": "adapterParams", "type": "bytes"}
                    ],
                    outputs=[
                        {"type": "uint256"},
                        {"type": "uint256"}
                    ],
                    state_mutability="view",
                    description="Estimate bridge fees",
                    category="read"
                ),
            ]
        )
        
        # Staking Contract (Generic)
        self.templates["staking_generic"] = ProtocolTemplate(
            protocol_type=ProtocolType.YIELD,
            contract_role=ContractRole.STAKING,
            standard_interfaces=["IStaking"],
            methods=[
                ContractMethod(
                    name="stake",
                    signature="stake(uint256)",
                    inputs=[{"name": "amount", "type": "uint256"}],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Stake tokens",
                    category="write",
                    gas_estimate=150000
                ),
                ContractMethod(
                    name="withdraw",
                    signature="withdraw(uint256)",
                    inputs=[{"name": "amount", "type": "uint256"}],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Withdraw staked tokens",
                    category="write",
                    gas_estimate=150000
                ),
                ContractMethod(
                    name="claimRewards",
                    signature="claimRewards()",
                    inputs=[],
                    outputs=[],
                    state_mutability="nonpayable",
                    description="Claim staking rewards",
                    category="write",
                    gas_estimate=100000
                ),
                ContractMethod(
                    name="earned",
                    signature="earned(address)",
                    inputs=[{"name": "account", "type": "address"}],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get earned rewards",
                    category="read"
                ),
                ContractMethod(
                    name="balanceOf",
                    signature="balanceOf(address)",
                    inputs=[{"name": "account", "type": "address"}],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get staked balance",
                    category="read"
                ),
                ContractMethod(
                    name="totalSupply",
                    signature="totalSupply()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get total staked",
                    category="read"
                ),
                ContractMethod(
                    name="rewardRate",
                    signature="rewardRate()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get reward rate per second",
                    category="read"
                ),
                ContractMethod(
                    name="periodFinish",
                    signature="periodFinish()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get reward period end",
                    category="read"
                ),
            ]
        )
        
        # Oracle / Price Feed (Chainlink style)
        self.templates["oracle_chainlink"] = ProtocolTemplate(
            protocol_type=ProtocolType.ORACLE,
            contract_role=ContractRole.PRICE_FEED,
            standard_interfaces=["AggregatorV3Interface"],
            methods=[
                ContractMethod(
                    name="latestAnswer",
                    signature="latestAnswer()",
                    inputs=[],
                    outputs=[{"type": "int256"}],
                    state_mutability="view",
                    description="Get latest price answer",
                    category="read"
                ),
                ContractMethod(
                    name="latestRoundData",
                    signature="latestRoundData()",
                    inputs=[],
                    outputs=[
                        {"type": "uint80"},
                        {"type": "int256"},
                        {"type": "uint256"},
                        {"type": "uint256"},
                        {"type": "uint80"}
                    ],
                    state_mutability="view",
                    description="Get latest round data",
                    category="read"
                ),
                ContractMethod(
                    name="decimals",
                    signature="decimals()",
                    inputs=[],
                    outputs=[{"type": "uint8"}],
                    state_mutability="view",
                    description="Get price decimals",
                    category="read"
                ),
                ContractMethod(
                    name="description",
                    signature="description()",
                    inputs=[],
                    outputs=[{"type": "string"}],
                    state_mutability="view",
                    description="Get feed description",
                    category="read"
                ),
                ContractMethod(
                    name="version",
                    signature="version()",
                    inputs=[],
                    outputs=[{"type": "uint256"}],
                    state_mutability="view",
                    description="Get aggregator version",
                    category="read"
                ),
            ]
        )
    
    def get_template(self, template_name: str) -> Optional[ProtocolTemplate]:
        """Get a protocol template by name."""
        return self.templates.get(template_name)
    
    def get_templates_by_type(self, protocol_type: ProtocolType) -> List[ProtocolTemplate]:
        """Get all templates for a protocol type."""
        return [t for t in self.templates.values() if t.protocol_type == protocol_type]
    
    def get_templates_by_role(self, contract_role: ContractRole) -> List[ProtocolTemplate]:
        """Get all templates for a contract role."""
        return [t for t in self.templates.values() if t.contract_role == contract_role]
    
    def list_templates(self) -> List[str]:
        """List all template names."""
        return list(self.templates.keys())
    
    def get_method_by_signature(self, template_name: str, signature: str) -> Optional[ContractMethod]:
        """Get a specific method by signature."""
        template = self.get_template(template_name)
        if template:
            for method in template.methods:
                if method.signature == signature:
                    return method
        return None


# Export singleton instance
catalog = ProtocolCatalog()