---
name: defillama-contract-verification-results
description: On-chain verification results for DefiLlama CLI contracts across 58 chains
---

## On-Chain Contract Verification Results

Tested 380 DEX factory contracts across 58 EVM chains using public RPCs.

### Results Summary
- **388/397 deployed (97.7%)** across 54 chains (dRPC API key)
- 50 chains at 100% deployment
- Only 6 empty (testnet contracts) and 3 errors (Manta RPC down)

### Verified Chains (100% deployed)
Ethereum (16), Binance (48), Arbitrum (22), Base (22), Polygon (21), Avalanche (18), Fantom (25), Sonic (16), Optimism (10), Blast (10), Mantle (10), Gnosis/XDai (5), Kava (8), Moonbeam (5), Moonriver (4), Astar (2), Boba (2), Filecoin (1), Fraxtal (2), Abstract (3), Arbitrum Nova (1), Aurora (4), Bob (1), Canto (2), Chiliz (2), Dogechain (1), Edu Chain (1), Flare (4), Fuse (4), Hyperliquid (8), Ink (4), Katana (1), Lisk (1), Megaeth (6), Monad (13), Omax (1), Polygon zkEVM (1), PulseChain (2), Scroll (9), SmartBCH (4), Sophon (1), Swellchain (1), Taiko (2), Unichain (1), XRPL EVM (2), ZkSync (8)

### Working RPCs (62 chains)
```python
live_rpcs = {
    "ethereum": "https://gateway.tenderly.co/public/mainnet",
    "binance": "https://bsc-dataseed.bnbchain.org",
    "arbitrum": "https://gateway.tenderly.co/public/arbitrum",
    "base": "https://gateway.tenderly.co/public/base",
    "polygon": "https://gateway.tenderly.co/public/polygon",
    "avalanche": "https://gateway.tenderly.co/public/avalanche",
    "optimism": "https://gateway.tenderly.co/public/optimism",
    "fantom": "https://rpcapi.fantom.network",
    "sonic": "https://gateway.tenderly.co/public/sonic",
    "mantle": "https://rpc.mantle.xyz",
    "blast": "https://rpc.blast.io",
    "gnosis": "https://rpc.gnosischain.com",
    "kava": "https://evm.kava.io",
    "celo": "https://forno.celo-sepolia.celo-testnet.org",
    "fraxtal": "https://fraxtal.gateway.tenderly.co",
    "moonriver": "https://moonriver.api.onfinality.io/public",
    "boba": "https://mainnet.boba.network",
    "filecoin": "https://api.node.glif.io",
    "moonbeam": "https://moonbeam.api.onfinality.io/public",
    "astar": "https://evm.astar.network",
    "abstract": "https://api.mainnet.abs.xyz",
    "arbitrum_nova": "https://arbitrum-nova.gateway.tenderly.co",
    "aurora": "https://aurora-mainnet.gateway.tatum.io",
    "berachain": "https://bepolia.rpc.berachain.com",
    "bob": "https://bob.gateway.tenderly.co",
    "canto": "https://canto.gravitychain.io",
    "chiliz": "https://rpc.ankr.com/chiliz",
    "edu_chain": "https://rpc.edu-chain.raas.gelato.cloud",
    "flare": "https://flare-api.flare.network/ext/C/rpc",
    "ink": "https://ink-public.nodies.app",
    "katana": "https://katana.gateway.tenderly.co",
    "lisk": "https://rpc.api.lisk.com",
    "megaeth": "https://rpc-megaeth-mainnet.globalstake.io",
    "omax": "https://mainapi.omaxray.com",
    "polygon_zkevm": "https://1rpc.io/polygon/zkevm",
    "scroll": "https://scroll.api.pocket.network",
    "smartbch": "https://smartbch.greyh.at",
    "sophon": "https://rpc.sophon.xyz",
    "swellchain": "https://rpc.ankr.com/swell",
    "unichain": "https://unichain.api.onfinality.io/public",
    "xrpl_evm": "https://rpc.xrplevm.org",
    "monad": "https://rpc.monad.xyz",
    "zksync": "https://mainnet.era.zksync.io",
    "hyperliquid": "https://rpc.hyperliquid.xyz/evm",
    "fuse": "https://rpc.fuse.io",
    "taiko": "https://rpc.mainnet.taiko.xyz",
    "pulsechain": "https://rpc.pulsechain.com",
    "dogechain": "https://rpc.dogechain.dog",
}
```

### Contract Check Function
```python
def check_contract(rpc, addr, timeout=8):
    import json, urllib.request, ssl
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getCode", "params": [addr, "latest"]}).encode()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(rpc, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
            code = result.get("result", "")
            if code and code != "0x" and len(code) > 2:
                return "deployed"
            return "empty"
    except:
        return "error"
```

### RPC Providers with API Keys
```python
# dRPC - 41+ chains
"drpc": "https://lb.drpc.live/{chain}/AiOf1Z6UG0c-kAdIiTtooY_53YKiO2kR8ZhQtiKh6MJI"
# Tenderly - 7 chains  
"tenderly": "https://{chain}.gateway.tenderly.co/-214OdMSEWayFfwzFYXB0chBAdGcJTmA"
# Ankr
"ankr": "https://rpc.ankr.com/{chain}/0e8c5d238f6a82f29d32988cccc7094b7435463936045a913be32563e16b5792"
# Onfinality
"onfinality": "https://{chain}.api.onfinality.io/public?apikey=313a88ce-4c24-4485-beab-0e091b369e7d"
```

### dRPC Chain Name Mappings
```python
drpc_map = {
    "ethereum": "ethereum", "binance": "bsc", "arbitrum": "arbitrum",
    "base": "base", "polygon": "polygon", "avalanche": "avalanche",
    "optimism": "optimism", "fantom": "fantom", "sonic": "sonic",
    "mantle": "mantle", "blast": "blast", "gnosis": "gnosis",
    "kava": "kava", "celo": "celo", "linea": "linea", "scroll": "scroll",
    "zksync": "zksync", "mode": "mode", "manta": "manta", "metis": "metis",
    "cronos": "cronos", "moonbeam": "moonbeam", "moonriver": "moonriver",
    "aurora": "aurora", "boba": "boba", "core": "core", "telos": "telos",
    "fuse": "fuse", "shibarium": "shibarium", "zora": "zora", "fraxtal": "fraxtal",
    "berachain": "berachain", "taiko": "taiko", "polygon_zkevm": "polygon-zkevm",
    "soneium": "soneium", "ink": "ink", "abstract": "abstract", "unichain": "unichain",
    "apechain": "apechain", "hyperliquid": "hyperliquid", "monad": "monad",
    "megaeth": "megaeth", "katana": "katana", "flow": "flow", "chiliz": "chiliz",
    "flare": "flare", "astar": "astar", "filecoin": "filecoin",
    "pulsechain": "pulsechain", "xdc": "xdc", "xrpl_evm": "xrpl-evm",
    "smartbch": "smartbch", "dogechain": "dogechain", "klaytn": "klaytn",
}
```

### Verified Chains at 100% (50 chains)
Binance (48), Fantom (25), Arbitrum (22), Base (22), Polygon (21), Avalanche (18), Ethereum (16), Sonic (16), Linea (13), Monad (13), Optimism (10), Blast (10), Mantle (10), Mode (10), Scroll (9), Metis (9), Kava (8), ZkSync (8), Hyperliquid (8), Core (6), Megaeth (6), Cronos (5), Moonbeam (5), Telos (5), XDAI (5), Aurora (4), Flare (4), Fuse (4), Ink (4), Moonriver (4), SmartBCH (4), Abstract (3), Klaytn (3), Apechain (2), Astar (2), Boba (2), Chiliz (2), Fraxtal (2), PulseChain (2), Shibarium (2), Soneium (2), Taiko (2), XRPL EVM (2), Celo (1), Dogechain (1), Filecoin (1), Katana (1), Polygon zkEVM (1), Unichain (1), Zora (1)

### Known Issues
- Manta RPC currently down
- Flow/Berachain/XDC: testnet contracts not deployed
- Arbitrum dRPC returns wrong data for some contracts - use Tenderly fallback

### Data Sources
- dimension-adapters/factory/uniV2.ts (254 V2 protocols)
- dimension-adapters/factory/uniV3.ts (97 V3 protocols)
- DefiLlama API (chains, protocols, DEXs)
- Verified RPC database (125 chains)
