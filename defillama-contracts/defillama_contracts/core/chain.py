#!/usr/bin/env python3
"""
Chain abstraction for blockchain networks.
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class ChainType(Enum):
    """Type of blockchain network."""
    EVM = "evm"
    SOLANA = "solana"
    COSMOS = "cosmos"
    OTHER = "other"


@dataclass
class ChainConfig:
    """Configuration for a blockchain chain."""
    name: str
    chain_id: Optional[int] = None
    chain_type: ChainType = ChainType.EVM
    rpc_urls: List[str] = None
    native_token: str = "ETH"
    native_token_decimals: int = 18
    block_time: int = 12  # seconds
    explorer_url: Optional[str] = None
    is_testnet: bool = False
    gas_price_oracle: Optional[str] = None
    multicall_address: Optional[str] = None
    
    def __post_init__(self):
        if self.rpc_urls is None:
            self.rpc_urls = []


class Chain:
    """
    Represents a blockchain network.
    
    Usage:
        # Create chain instance
        chain = Chain("Ethereum", chain_id=1)
        
        # Get chain info
        print(chain.name)  # "Ethereum"
        print(chain.chain_id)  # 1
        
        # Check chain type
        if chain.is_evm():
            print("EVM compatible chain")
    """
    
    # Chain configurations
    CHAIN_CONFIGS: Dict[str, ChainConfig] = {
        "Ethereum": ChainConfig(
            name="Ethereum",
            chain_id=1,
            chain_type=ChainType.EVM,
            rpc_urls=[
                "https://lb.drpc.live/ethereum/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI",
                "https://eth.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d",
                "https://rpc.ankr.com/eth/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
            ],
            native_token="ETH",
            block_time=12,
            explorer_url="https://etherscan.io",
            multicall_address="0xcA11bde05977b3631167028862bE2a173976CA11"
        ),
        "Binance": ChainConfig(
            name="Binance",
            chain_id=56,
            chain_type=ChainType.EVM,
            rpc_urls=[
                "https://lb.drpc.live/bsc/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI",
                "https://bsc.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d",
                "https://rpc.ankr.com/bsc/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
            ],
            native_token="BNB",
            block_time=3,
            explorer_url="https://bscscan.com",
            multicall_address="0xcA11bde05977b3631167028862bE2a173976CA11"
        ),
        "Arbitrum": ChainConfig(
            name="Arbitrum",
            chain_id=42161,
            chain_type=ChainType.EVM,
            rpc_urls=[
                "https://lb.drpc.live/arbitrum/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI",
                "https://arbitrum.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d",
                "https://rpc.ankr.com/arbitrum/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
            ],
            native_token="ETH",
            block_time=0.25,
            explorer_url="https://arbiscan.io",
            multicall_address="0xcA11bde05977b3631167028862bE2a173976CA11"
        ),
        "Base": ChainConfig(
            name="Base",
            chain_id=8453,
            chain_type=ChainType.EVM,
            rpc_urls=[
                "https://lb.drpc.live/base/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI",
                "https://base.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d",
                "https://rpc.ankr.com/base/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
            ],
            native_token="ETH",
            block_time=2,
            explorer_url="https://basescan.org",
            multicall_address="0xcA11bde05977b3631167028862bE2a173976CA11"
        ),
        "Polygon": ChainConfig(
            name="Polygon",
            chain_id=137,
            chain_type=ChainType.EVM,
            rpc_urls=[
                "https://lb.drpc.live/polygon/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI",
                "https://polygon.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d",
                "https://rpc.ankr.com/polygon/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
            ],
            native_token="MATIC",
            block_time=2,
            explorer_url="https://polygonscan.com",
            multicall_address="0xcA11bde05977b3631167028862bE2a173976CA11"
        ),
        "Avalanche": ChainConfig(
            name="Avalanche",
            chain_id=43114,
            chain_type=ChainType.EVM,
            rpc_urls=[
                "https://lb.drpc.live/avalanche/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI",
                "https://avalanche.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d",
                "https://rpc.ankr.com/avalanche/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
            ],
            native_token="AVAX",
            block_time=2,
            explorer_url="https://snowtrace.io",
            multicall_address="0xcA11bde05977b3631167028862bE2a173976CA11"
        ),
        "Optimism": ChainConfig(
            name="Optimism",
            chain_id=10,
            chain_type=ChainType.EVM,
            rpc_urls=[
                "https://lb.drpc.live/optimism/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI",
                "https://optimism.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d",
                "https://rpc.ankr.com/optimism/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
            ],
            native_token="ETH",
            block_time=2,
            explorer_url="https://optimistic.etherscan.io",
            multicall_address="0xcA11bde05977b3631167028862bE2a173976CA11"
        ),
        "Fantom": ChainConfig(
            name="Fantom",
            chain_id=250,
            chain_type=ChainType.EVM,
            rpc_urls=[
                "https://lb.drpc.live/fantom/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI",
                "https://fantom.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d",
                "https://rpc.ankr.com/fantom/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
            ],
            native_token="FTM",
            block_time=1,
            explorer_url="https://ftmscan.com",
            multicall_address="0xcA11bde05977b3631167028862bE2a173976CA11"
        ),
        "Solana": ChainConfig(
            name="Solana",
            chain_id=None,
            chain_type=ChainType.SOLANA,
            rpc_urls=[
                "https://api.mainnet-beta.solana.com",
                "https://rpc.ankr.com/solana"
            ],
            native_token="SOL",
            native_token_decimals=9,
            block_time=0.4,
            explorer_url="https://explorer.solana.com"
        ),
    }
    
    def __init__(
        self,
        name: str,
        chain_id: Optional[int] = None,
        rpc_urls: Optional[List[str]] = None,
        native_token: str = "ETH",
        block_time: int = 12,
        chain_type: ChainType = ChainType.EVM
    ):
        """
        Initialize a chain instance.
        
        Args:
            name: Chain name
            chain_id: Chain ID (for EVM chains)
            rpc_urls: List of RPC URLs
            native_token: Native token symbol
            block_time: Block time in seconds
            chain_type: Type of blockchain
        """
        self.name = name
        self.chain_id = chain_id
        self.native_token = native_token
        self.block_time = block_time
        self.chain_type = chain_type
        
        # Use provided RPC URLs or get from config
        if rpc_urls:
            self.rpc_urls = rpc_urls
        elif name in self.CHAIN_CONFIGS:
            self.rpc_urls = self.CHAIN_CONFIGS[name].rpc_urls
        else:
            self.rpc_urls = []
        
        # Get other config from predefined chains
        if name in self.CHAIN_CONFIGS:
            config = self.CHAIN_CONFIGS[name]
            self.explorer_url = config.explorer_url
            self.multicall_address = config.multicall_address
            self.native_token_decimals = config.native_token_decimals
            self.is_testnet = config.is_testnet
        else:
            self.explorer_url = None
            self.multicall_address = None
            self.native_token_decimals = 18
            self.is_testnet = False
    
    def is_evm(self) -> bool:
        """Check if chain is EVM compatible."""
        return self.chain_type == ChainType.EVM
    
    def is_solana(self) -> bool:
        """Check if chain is Solana."""
        return self.chain_type == ChainType.SOLANA
    
    def get_explorer_url(self, address: str = None) -> str:
        """
        Get block explorer URL.
        
        Args:
            address: Optional address to include in URL
            
        Returns:
            Explorer URL
        """
        if not self.explorer_url:
            return ""
        
        if address:
            return f"{self.explorer_url}/address/{address}"
        return self.explorer_url
    
    def get_rpc_url(self, index: int = 0) -> Optional[str]:
        """
        Get RPC URL by index.
        
        Args:
            index: RPC URL index
            
        Returns:
            RPC URL or None if index out of range
        """
        if 0 <= index < len(self.rpc_urls):
            return self.rpc_urls[index]
        return None
    
    def add_rpc_url(self, url: str):
        """
        Add RPC URL to chain.
        
        Args:
            url: RPC URL to add
        """
        if url not in self.rpc_urls:
            self.rpc_urls.append(url)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert chain to dictionary."""
        return {
            "name": self.name,
            "chain_id": self.chain_id,
            "chain_type": self.chain_type.value,
            "rpc_urls": self.rpc_urls,
            "native_token": self.native_token,
            "native_token_decimals": self.native_token_decimals,
            "block_time": self.block_time,
            "explorer_url": self.explorer_url,
            "multicall_address": self.multicall_address,
            "is_testnet": self.is_testnet
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Chain':
        """Create chain from dictionary."""
        return cls(
            name=data["name"],
            chain_id=data.get("chain_id"),
            rpc_urls=data.get("rpc_urls"),
            native_token=data.get("native_token", "ETH"),
            block_time=data.get("block_time", 12),
            chain_type=ChainType(data.get("chain_type", "evm"))
        )
    
    @classmethod
    def get_chain(cls, name: str) -> Optional['Chain']:
        """
        Get chain by name.
        
        Args:
            name: Chain name
            
        Returns:
            Chain instance or None if not found
        """
        if name in cls.CHAIN_CONFIGS:
            config = cls.CHAIN_CONFIGS[name]
            return cls(
                name=name,
                chain_id=config.chain_id,
                rpc_urls=config.rpc_urls,
                native_token=config.native_token,
                block_time=config.block_time,
                chain_type=config.chain_type
            )
        return None
    
    @classmethod
    def get_all_chains(cls) -> List['Chain']:
        """Get all predefined chains."""
        return [cls.get_chain(name) for name in cls.CHAIN_CONFIGS.keys()]
    
    @classmethod
    def get_evm_chains(cls) -> List['Chain']:
        """Get all EVM chains."""
        return [chain for chain in cls.get_all_chains() if chain.is_evm()]
    
    def __str__(self):
        return f"Chain({self.name})"
    
    def __repr__(self):
        return f"<Chain name={self.name} chain_id={self.chain_id}>"