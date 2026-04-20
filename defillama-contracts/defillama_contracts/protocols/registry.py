#!/usr/bin/env python3
"""
Protocol Registry - Maps specific protocols to their contract patterns and addresses.
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import ProtocolType, ContractRole, ProtocolTemplate, catalog


@dataclass
class ProtocolDefinition:
    """Definition of a specific protocol."""
    name: str
    protocol_type: ProtocolType
    chains: List[str] = field(default_factory=list)
    contracts: Dict[str, List[str]] = field(default_factory=dict)  # role -> [addresses]
    templates: Dict[str, str] = field(default_factory=dict)  # role -> template_name
    version: str = ""
    website: str = ""
    docs: str = ""
    github: str = ""
    notes: str = ""


class ProtocolRegistry:
    """Registry of known protocols with their contract addresses and templates."""
    
    def __init__(self):
        self.protocols: Dict[str, ProtocolDefinition] = {}
        self._initialize_known_protocols()
    
    def _initialize_known_protocols(self):
        """Initialize known protocols from DefiLlama and common DeFi protocols."""
        
        # Uniswap V2
        self.protocols["uniswap_v2"] = ProtocolDefinition(
            name="Uniswap V2",
            protocol_type=ProtocolType.DEX,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Binance", "Avalanche"],
            contracts={
                "router": [
                    "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",  # Ethereum
                ],
                "factory": [
                    "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",  # Ethereum
                ]
            },
            templates={
                "router": "uniswap_v2_router",
                "factory": "uniswap_v2_factory",
                "pair": "uniswap_v2_pair"
            },
            version="2.0",
            website="https://uniswap.org",
            docs="https://docs.uniswap.org/contracts/v2/overview",
            github="https://github.com/Uniswap/v2-core"
        )
        
        # Uniswap V3
        self.protocols["uniswap_v3"] = ProtocolDefinition(
            name="Uniswap V3",
            protocol_type=ProtocolType.DEX,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Base", "Avalanche", "Binance"],
            contracts={
                "router": [
                    "0xE592427A0AEce92De3Edee1F18E0157C05861564",  # SwapRouter
                    "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",  # SwapRouter02
                ],
                "factory": [
                    "0x1F98431c8aD98523631AE4a59f267346ea31F984",  # Ethereum
                ]
            },
            templates={
                "router": "uniswap_v3_router",
                "factory": "uniswap_v3_factory"
            },
            version="3.0",
            website="https://uniswap.org",
            docs="https://docs.uniswap.org/contracts/v3/overview",
            github="https://github.com/Uniswap/v3-core"
        )
        
        # Curve Finance
        self.protocols["curve"] = ProtocolDefinition(
            name="Curve Finance",
            protocol_type=ProtocolType.DEX,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Avalanche", "Fantom", "Base"],
            contracts={
                "router": [
                    "0x99a58482BD75cbab83b27EC03CA68fF489b5788f",  # Curve Router
                    "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7",  # 3pool
                ]
            },
            templates={
                "router": "curve_router"
            },
            version="1.0",
            website="https://curve.fi",
            docs="https://curve.readthedocs.io",
            github="https://github.com/curvefi/curve-contract"
        )
        
        # Aave V3
        self.protocols["aave_v3"] = ProtocolDefinition(
            name="Aave V3",
            protocol_type=ProtocolType.LENDING,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Avalanche", "Fantom", "Base", "Gnosis", "Binance"],
            contracts={
                "lending_pool": [
                    "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",  # Ethereum Pool
                    "0x794a61358D6845594F94dc1DB02A252b5b4814aD",  # Arbitrum Pool
                ],
                "oracle": [
                    "0x54586bE62E3c3580375aE3723C145253060Ca0C2",  # Ethereum Oracle
                ]
            },
            templates={
                "lending_pool": "aave_v3_pool"
            },
            version="3.0",
            website="https://aave.com",
            docs="https://docs.aave.com",
            github="https://github.com/aave/aave-v3-core"
        )
        
        # Compound V3 (Comet)
        self.protocols["compound_v3"] = ProtocolDefinition(
            name="Compound V3",
            protocol_type=ProtocolType.LENDING,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Base"],
            contracts={
                "lending_pool": [
                    "0xc3d688B66703497DAA19211EEdff47f25384cdc3",  # cUSDCv3 Ethereum
                    "0xA17581A9E3356d9A858b789D68B4d866e593aE94",  # cWETHv3 Ethereum
                ]
            },
            templates={
                "lending_pool": "aave_v3_pool"  # Similar interface
            },
            version="3.0",
            website="https://compound.finance",
            docs="https://docs.compound.finance",
            github="https://github.com/compound-finance/compound-v3"
        )
        
        # Lido
        self.protocols["lido"] = ProtocolDefinition(
            name="Lido",
            protocol_type=ProtocolType.YIELD,
            chains=["Ethereum"],
            contracts={
                "staking": [
                    "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",  # stETH
                ],
                "token": [
                    "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",  # stETH
                    "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",  # wstETH
                ]
            },
            templates={
                "staking": "staking_generic"
            },
            version="1.0",
            website="https://lido.fi",
            docs="https://docs.lido.fi",
            github="https://github.com/lidofinance/lido-dao"
        )
        
        # Chainlink Oracle
        self.protocols["chainlink"] = ProtocolDefinition(
            name="Chainlink",
            protocol_type=ProtocolType.ORACLE,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Avalanche", "Binance", "Base", "Fantom"],
            contracts={
                "price_feed": [
                    "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",  # ETH/USD
                    "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",  # BTC/USD
                    "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",  # USDC/USD
                ]
            },
            templates={
                "price_feed": "oracle_chainlink"
            },
            version="1.0",
            website="https://chain.link",
            docs="https://docs.chain.link",
            github="https://github.com/smartcontractkit/chainlink"
        )
        
        # Stargate Bridge
        self.protocols["stargate"] = ProtocolDefinition(
            name="Stargate Finance",
            protocol_type=ProtocolType.BRIDGE,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Avalanche", "Binance", "Base", "Fantom"],
            contracts={
                "bridge": [
                    "0x8731d54E9D02c286767d56ac03e8037C07e01e98",  # StargateRouter Ethereum
                ]
            },
            templates={
                "bridge": "bridge_generic"
            },
            version="1.0",
            website="https://stargate.finance",
            docs="https://stargateprotocol.gitbook.io",
            github="https://github.com/stargate-protocol"
        )
        
        # LayerZero Bridge
        self.protocols["layerzero"] = ProtocolDefinition(
            name="LayerZero",
            protocol_type=ProtocolType.BRIDGE,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Avalanche", "Binance", "Base", "Fantom"],
            contracts={
                "bridge": [
                    "0x66A71Dcef29A0fFBDBE3c6a460a3B5BC225Cd675",  # LayerZero Endpoint
                ]
            },
            templates={
                "bridge": "bridge_generic"
            },
            version="1.0",
            website="https://layerzero.network",
            docs="https://layerzero.gitbook.io",
            github="https://github.com/LayerZero-Labs"
        )
        
        # MakerDAO
        self.protocols["makerdao"] = ProtocolDefinition(
            name="MakerDAO",
            protocol_type=ProtocolType.STABLECOIN,
            chains=["Ethereum"],
            contracts={
                "vault": [
                    "0x9759A6Ac90977b93B58547b4A71c78317f391A28",  # DAI Join
                ],
                "token": [
                    "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # DAI
                ]
            },
            templates={
                "vault": "aave_v3_pool"  # Similar lending interface
            },
            version="1.0",
            website="https://makerdao.com",
            docs="https://docs.makerdao.com",
            github="https://github.com/makerdao"
        )
        
        # Morpho
        self.protocols["morpho"] = ProtocolDefinition(
            name="Morpho",
            protocol_type=ProtocolType.LENDING,
            chains=["Ethereum", "Base"],
            contracts={
                "lending_pool": [
                    "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb",  # Morpho Blue
                ]
            },
            templates={
                "lending_pool": "aave_v3_pool"  # Similar interface
            },
            version="1.0",
            website="https://morpho.org",
            docs="https://docs.morpho.org",
            github="https://github.com/morpho-org"
        )
        
        # Aerodrome (Base DEX)
        self.protocols["aerodrome"] = ProtocolDefinition(
            name="Aerodrome",
            protocol_type=ProtocolType.DEX,
            chains=["Base"],
            contracts={
                "router": [
                    "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43",  # Aerodrome Router
                ],
                "factory": [
                    "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",  # Aerodrome Factory
                ]
            },
            templates={
                "router": "uniswap_v2_router",  # Similar interface
                "factory": "uniswap_v2_factory",
                "pair": "uniswap_v2_pair"
            },
            version="1.0",
            website="https://aerodrome.finance",
            docs="https://docs.aerodrome.finance",
            github="https://github.com/aerodrome-finance"
        )
        
        # Velodrome (Optimism DEX)
        self.protocols["velodrome"] = ProtocolDefinition(
            name="Velodrome",
            protocol_type=ProtocolType.DEX,
            chains=["Optimism"],
            contracts={
                "router": [
                    "0x9c12939390052919aF3155f41Bf4160Fd3666A6f",  # Velodrome Router
                ],
                "factory": [
                    "0x25CbdDb98b35ab1FF77413456B31EC81A6B6B746",  # Velodrome Factory
                ]
            },
            templates={
                "router": "uniswap_v2_router",
                "factory": "uniswap_v2_factory",
                "pair": "uniswap_v2_pair"
            },
            version="1.0",
            website="https://velodrome.finance",
            docs="https://docs.velodrome.finance",
            github="https://github.com/velodrome-finance"
        )
        
        # PancakeSwap
        self.protocols["pancakeswap"] = ProtocolDefinition(
            name="PancakeSwap",
            protocol_type=ProtocolType.DEX,
            chains=["Binance", "Ethereum", "Arbitrum", "Polygon", "Base"],
            contracts={
                "router": [
                    "0x10ED43C718714eb63d5aA57B78B54704E256024E",  # BSC Router V2
                    "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4",  # Ethereum Router V2
                ],
                "factory": [
                    "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",  # BSC Factory V2
                ]
            },
            templates={
                "router": "uniswap_v2_router",
                "factory": "uniswap_v2_factory",
                "pair": "uniswap_v2_pair"
            },
            version="2.0",
            website="https://pancakeswap.finance",
            docs="https://docs.pancakeswap.finance",
            github="https://github.com/pancakeswap"
        )
        
        # SushiSwap
        self.protocols["sushiswap"] = ProtocolDefinition(
            name="SushiSwap",
            protocol_type=ProtocolType.DEX,
            chains=["Ethereum", "Arbitrum", "Polygon", "Optimism", "Avalanche", "Binance", "Base", "Fantom"],
            contracts={
                "router": [
                    "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F",  # Ethereum Router
                ],
                "factory": [
                    "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac",  # Ethereum Factory
                ]
            },
            templates={
                "router": "uniswap_v2_router",
                "factory": "uniswap_v2_factory",
                "pair": "uniswap_v2_pair"
            },
            version="2.0",
            website="https://sushi.com",
            docs="https://docs.sushi.com",
            github="https://github.com/sushiswap"
        )
    
    def get_protocol(self, name: str) -> Optional[ProtocolDefinition]:
        """Get a protocol by name."""
        return self.protocols.get(name.lower())
    
    def get_protocols_by_type(self, protocol_type: ProtocolType) -> List[ProtocolDefinition]:
        """Get all protocols of a specific type."""
        return [p for p in self.protocols.values() if p.protocol_type == protocol_type]
    
    def get_protocols_by_chain(self, chain: str) -> List[ProtocolDefinition]:
        """Get all protocols on a specific chain."""
        return [p for p in self.protocols.values() if chain in p.chains]
    
    def find_protocol_by_address(self, address: str, chain: str) -> Optional[tuple]:
        """Find protocol and role for a specific contract address."""
        for name, protocol in self.protocols.items():
            if chain in protocol.chains:
                for role, addresses in protocol.contracts.items():
                    if address.lower() in [a.lower() for a in addresses]:
                        return (name, protocol, role)
        return None
    
    def get_template_for_contract(self, protocol_name: str, role: str) -> Optional[ProtocolTemplate]:
        """Get the protocol template for a specific contract role."""
        protocol = self.get_protocol(protocol_name)
        if not protocol:
            return None
        
        template_name = protocol.templates.get(role)
        if not template_name:
            return None
        
        return catalog.get_template(template_name)
    
    def list_protocols(self) -> List[str]:
        """List all protocol names."""
        return list(self.protocols.keys())
    
    def list_all_contracts(self) -> Dict[str, Any]:
        """List all registered contracts across all protocols."""
        result = {}
        for name, protocol in self.protocols.items():
            result[name] = {
                "type": protocol.protocol_type.value,
                "chains": protocol.chains,
                "contracts": protocol.contracts,
                "version": protocol.version
            }
        return result


# Export singleton instance
registry = ProtocolRegistry()