"""
DefiLlama Unified Module
Comprehensive DeFi infrastructure from DefiLlama repos.

Data Sources:
  1. DefiLlama-Adapters/registries - DEX factory, lending, staking addresses
  2. dimension-adapters/factory - V2/V3 DEX factory addresses per chain
  3. bridges-server/adapters - Bridge contract addresses and event ABIs
  4. yield-server/adaptors - Yield protocol addresses
  5. chainlist/constants - RPC endpoints for 585+ chains
  6. defillama-sdk/providers - RPC providers for 158 chains
  7. DefiLlama-Adapters/coreAssets.json - Canonical token addresses for 356 chains
  8. defi_protocol_registry.json - 1,952 protocols with TVL/category/chains

Usage:
  import defillama_unified as dlu
  
  # Get all DEX factories on a chain
  dlu.get_dex_factories('base')
  
  # Get RPC endpoints for a chain
  dlu.get_rpcs('ethereum')
  
  # Get bridge adapters
  dlu.get_bridge_adapters()
  
  # Get core assets (WETH, USDC, etc.) for a chain
  dlu.get_core_assets('ethereum')
  
  # Get all protocols on a chain
  dlu.get_protocols('base')
"""
import json
import os
from pathlib import Path
from functools import lru_cache
from typing import Dict, List, Optional, Any, Set

# Data directory
DATA_DIR = Path.home() / ".hermes" / "data" / "defillama_unified"

# Chain name aliases
CHAIN_ALIASES = {
    'ethereum': 'ethereum', 'eth': 'ethereum',
    'bsc': 'binance', 'binance': 'binance', 'bnb': 'binance',
    'polygon': 'polygon', 'matic': 'polygon',
    'avalanche': 'avalanche', 'avax': 'avalanche',
    'fantom': 'fantom', 'ftm': 'fantom',
    'arbitrum': 'arbitrum', 'arb': 'arbitrum',
    'optimism': 'optimism', 'op': 'optimism', 'op mainnet': 'optimism', 'op_mainnet': 'optimism',
    'base': 'base',
    'xdai': 'xdai', 'gnosis': 'xdai', 'gno': 'xdai',
    'solana': 'solana', 'sol': 'solana',
    'tron': 'tron', 'trx': 'tron',
    'starknet': 'starknet',
    'cronos': 'cronos', 'cro': 'cronos',
    'celo': 'celo',
    'moonbeam': 'moonbeam', 'glmr': 'moonbeam',
    'moonriver': 'moonriver', 'movr': 'moonriver',
    'aurora': 'aurora',
    'harmony': 'harmony', 'one': 'harmony',
    'boba': 'boba',
    'metis': 'metis',
    'klaytn': 'klaytn', 'klay': 'klaytn',
    'heco': 'heco',
    'okexchain': 'okexchain', 'okc': 'okexchain',
    'fuse': 'fuse',
    'evmos': 'evmos',
    'canto': 'canto',
    'zksync': 'zksync', 'zksync_era': 'zksync', 'era': 'zksync',
    'mantle': 'mantle',
    'linea': 'linea',
    'scroll': 'scroll',
    'manta': 'manta',
    'blast': 'blast',
    'mode': 'mode',
    'fraxtal': 'fraxtal',
    'sei': 'sei',
    'rootstock': 'rootstock', 'rsk': 'rootstock',
    'iota': 'iota',
    'shimmer_evm': 'shimmer', 'shimmer': 'shimmer',
    'taiko': 'taiko',
    'bittensor': 'bittensor',
    'corn': 'corn',
    'dydx': 'dydx',
    'kinto': 'kinto',
    'hyperliquid': 'hyperliquid',
    'sonic': 'sonic',
    'abstract': 'abstract',
    'apechain': 'apechain',
    'gravity': 'gravity',
    'rari': 'rari',
    'reya': 'reya',
    'ink': 'ink',
    'zero': 'zero',
    'monad': 'monad',
    'kava': 'kava',
    'core': 'core',
    'dfk': 'dfk',
    'thundercore': 'thundercore',
    'tomochain': 'tomochain',
    'iotex': 'iotex',
    'kcc': 'kcc',
    'oasys': 'oasys',
    'nahmii': 'nahmii',
    'sx': 'sx',
    'zyx': 'zyx',
    'wemix': 'wemix',
    'elastos': 'elastos',
    'milkomeda': 'milkomeda',
    'dogechain': 'dogechain',
    'ethpow': 'ethpow',
    'csc': 'csc',
    'europa': 'europa',
    'clv': 'clv',
    'ultron': 'ultron',
    'step': 'step',
    'tombchain': 'tombchain',
    'kekchain': 'kekchain',
    'godwoken': 'godwoken',
    'rei': 'rei',
    'bitgert': 'bitgert',
    'conflux': 'conflux',
    'oasis': 'oasis',
    'velas': 'velas',
    'astar': 'astar',
    'shiden': 'shiden',
    'wanchain': 'wanchain',
    'meter': 'meter',
    'starcoin': 'starcoin',
    'kardia': 'kardia',
    'vitae': 'vitae',
    'hoo': 'hoo',
    'bifrost': 'bifrost',
    'ethernity': 'ethernity',
    'exosama': 'exosama',
    'findora': 'findora',
    'fuse_old': 'fuse',
    'heiko': 'heiko',
    'parallel': 'parallel',
    'pego': 'pego',
    'pirl': 'pirl',
    'smartbch': 'smartbch',
    'syscoin': 'syscoin',
    'telos': 'telos',
    'wan': 'wanchain',
    'wax': 'wax',
    'xdc': 'xdc',
}

# Chain ID -> name mapping
CHAIN_ID_TO_NAME = {
    '1': 'ethereum', '56': 'binance', '137': 'polygon', '43114': 'avalanche',
    '250': 'fantom', '42161': 'arbitrum', '10': 'optimism', '8453': 'base',
    '100': 'xdai', '1284': 'moonbeam', '1285': 'moonriver', '1313161554': 'aurora',
    '1666600000': 'harmony', '288': 'boba', '1088': 'metis', '53935': 'dfk',
    '8217': 'klaytn', '128': 'heco', '66': 'okexchain', '122': 'fuse',
    '9001': 'evmos', '7700': 'canto', '324': 'zksync', '5000': 'mantle',
    '59144': 'linea', '534352': 'scroll', '169': 'manta', '81457': 'blast',
    '34443': 'mode', '252': 'fraxtal', '1329': 'sei', '30': 'rootstock',
    '8822': 'iota', '148': 'shimmer', '167000': 'taiko',
    '728126428': 'tron',
    '11155111': 'sepolia', '421614': 'arbitrum-sepolia',
    '84532': 'base-sepolia', '11155420': 'optimism-sepolia',
}

def normalize_chain(name: str) -> str:
    """Normalize chain name to canonical form."""
    if not name:
        return 'unknown'
    name = str(name).lower().strip()
    # Try chain ID first
    if name.isdigit() and name in CHAIN_ID_TO_NAME:
        return CHAIN_ID_TO_NAME[name]
    return CHAIN_ALIASES.get(name, name)


def _load_json(filename: str) -> Any:
    """Load a JSON file from the data directory."""
    filepath = DATA_DIR / filename
    if filepath.exists():
        with open(filepath) as f:
            return json.load(f)
    return {}


class DefiLlamaUnified:
    """Unified interface to all DefiLlama infrastructure data."""
    
    def __init__(self):
        self._chains = None
        self._protocols = None
        self._dex_factories = None
        self._bridge_adapters = None
        self._yield_adaptors = None
        self._rpc_endpoints = None
        self._core_assets = None
        self._chain_id_map = None
        self._registry_addresses = None
        self._chain_summary = None
        self._loaded = False
    
    def _load_all(self):
        """Load all data files."""
        if self._loaded:
            return
        
        data = _load_json("unified_defi_infrastructure.json")
        if data:
            self._chains = data.get('chains', {})
            self._protocols = data.get('protocols', {})
            self._dex_factories = data.get('dex_factories', {})
            self._bridge_adapters = data.get('bridge_adapters', {})
            self._yield_adaptors = data.get('yield_adaptors', {})
            self._rpc_endpoints = data.get('rpc_endpoints', {})
            self._core_assets = data.get('core_assets', {})
        
        self._chain_id_map = _load_json("chain_id_mapping.json")
        self._registry_addresses = _load_json("registry_addresses.json")
        self._chain_summary = _load_json("chain_summary.json")
        
        self._loaded = True
    
    @property
    def total_chains(self) -> int:
        self._load_all()
        return len(self._chains)
    
    @property
    def total_protocols(self) -> int:
        self._load_all()
        return len(self._protocols)
    
    def get_chains(self) -> List[str]:
        """Get all chain names."""
        self._load_all()
        return sorted(self._chains.keys())
    
    def get_chain_info(self, chain: str) -> Dict:
        """Get full info for a specific chain."""
        self._load_all()
        chain = normalize_chain(chain)
        return self._chains.get(chain, {})
    
    def get_dex_factories(self, chain: str) -> List[Dict]:
        """Get all DEX factory addresses on a chain."""
        self._load_all()
        chain = normalize_chain(chain)
        chain_data = self._chains.get(chain, {})
        return chain_data.get('dex_factories', [])
    
    def get_dex_factories_by_protocol(self, protocol: str, version: str = None) -> Dict[str, List[str]]:
        """Get DEX factories for a protocol across all chains.
        Returns: {chain: [factory_address, ...]}
        """
        self._load_all()
        if version:
            key = f"{protocol}/{version}"
            return self._dex_factories.get(key, {})
        
        # Search without version
        result = {}
        for key, chains in self._dex_factories.items():
            if key.startswith(f"{protocol}/"):
                for chain, addrs in chains.items():
                    if chain not in result:
                        result[chain] = []
                    result[chain].extend(addrs)
        return result
    
    def get_rpcs(self, chain: str) -> List[str]:
        """Get RPC endpoints for a chain."""
        self._load_all()
        chain = normalize_chain(chain)
        
        # Try by name
        rpcs = self._rpc_endpoints.get(chain, [])
        if rpcs:
            return rpcs
        
        # Try by chain ID
        for cid, name in self._chain_id_map.items():
            if name == chain:
                cid_rpcs = self._rpc_endpoints.get(cid, [])
                if cid_rpcs:
                    return cid_rpcs
        
        return []
    
    def get_core_assets(self, chain: str) -> Dict[str, str]:
        """Get canonical token addresses (WETH, USDC, etc.) for a chain."""
        self._load_all()
        chain = normalize_chain(chain)
        return self._core_assets.get(chain, {})
    
    def get_bridge_adapters(self) -> Dict[str, Dict]:
        """Get all bridge adapter data."""
        self._load_all()
        return self._bridge_adapters
    
    def get_bridges_on_chain(self, chain: str) -> List[Dict]:
        """Get bridge adapters active on a specific chain."""
        self._load_all()
        chain = normalize_chain(chain)
        chain_data = self._chains.get(chain, {})
        return chain_data.get('bridges', [])
    
    def get_yield_adaptors(self) -> Dict[str, Dict]:
        """Get all yield protocol adaptors."""
        self._load_all()
        return self._yield_adaptors
    
    def get_protocols(self, chain: str = None) -> List[Dict]:
        """Get protocols, optionally filtered by chain."""
        self._load_all()
        if chain:
            chain = normalize_chain(chain)
            return [
                p for p in self._protocols.values()
                if chain in [normalize_chain(c) for c in p.get('chains', [])]
            ]
        return list(self._protocols.values())
    
    def get_lending_protocols(self, chain: str) -> List[Dict]:
        """Get lending protocol addresses on a chain."""
        self._load_all()
        chain = normalize_chain(chain)
        chain_data = self._chains.get(chain, {})
        return chain_data.get('lending_protocols', [])
    
    def get_registry_addresses(self, registry: str = None) -> Dict:
        """Get addresses from DefiLlama-Adapters registries.
        Registries: uniswapV2, uniswapV3, compound, aave, masterchef, etc.
        """
        self._load_all()
        if registry:
            return self._registry_addresses.get(registry, {})
        return self._registry_addresses
    
    def get_chain_summary(self) -> Dict:
        """Get chain summary with counts."""
        self._load_all()
        return self._chain_summary
    
    def search_protocol(self, name: str) -> List[Dict]:
        """Search for a protocol by name (fuzzy)."""
        self._load_all()
        name_lower = name.lower()
        results = []
        for proto_name, info in self._protocols.items():
            if name_lower in proto_name.lower() or name_lower in info.get('slug', '').lower():
                results.append({'name': proto_name, **info})
        return results
    
    def get_all_chain_dex_count(self) -> Dict[str, int]:
        """Get DEX factory count per chain."""
        self._load_all()
        return {
            chain: len(data.get('dex_factories', []))
            for chain, data in self._chains.items()
        }
    
    def get_top_chains(self, by: str = 'dex', n: int = 20) -> List[tuple]:
        """Get top N chains by DEX count, lending count, or bridge count."""
        self._load_all()
        if by == 'dex':
            key = 'dex_factories'
        elif by == 'lending':
            key = 'lending_protocols'
        elif by == 'bridges':
            key = 'bridges'
        else:
            key = 'dex_factories'
        
        sorted_chains = sorted(
            self._chains.items(),
            key=lambda x: len(x[1].get(key, [])),
            reverse=True
        )
        return [(chain, len(data.get(key, []))) for chain, data in sorted_chains[:n]]


# Singleton instance
_instance = None

def get_instance() -> DefiLlamaUnified:
    """Get the singleton DefiLlamaUnified instance."""
    global _instance
    if _instance is None:
        _instance = DefiLlamaUnified()
    return _instance


# Convenience functions
def get_dex_factories(chain: str) -> List[Dict]:
    return get_instance().get_dex_factories(chain)

def get_rpcs(chain: str) -> List[str]:
    return get_instance().get_rpcs(chain)

def get_core_assets(chain: str) -> Dict[str, str]:
    return get_instance().get_core_assets(chain)

def get_bridge_adapters() -> Dict[str, Dict]:
    return get_instance().get_bridge_adapters()

def get_protocols(chain: str = None) -> List[Dict]:
    return get_instance().get_protocols(chain)

def get_lending_protocols(chain: str) -> List[Dict]:
    return get_instance().get_lending_protocols(chain)

def get_chain_info(chain: str) -> Dict:
    return get_instance().get_chain_info(chain)

def get_chains() -> List[str]:
    return get_instance().get_chains()

def get_top_chains(by: str = 'dex', n: int = 20) -> List[tuple]:
    return get_instance().get_top_chains(by, n)

def search_protocol(name: str) -> List[Dict]:
    return get_instance().search_protocol(name)


# Constants for external use
TOTAL_CHAINS = 2437
TOTAL_PROTOCOLS = 1952
TOTAL_DEX_FACTORIES = 892
TOTAL_BRIDGE_ADAPTERS = 86
TOTAL_YIELD_ADAPTORS = 658
TOTAL_RPC_CHAINS = 743
TOTAL_CORE_ASSET_CHAINS = 354
