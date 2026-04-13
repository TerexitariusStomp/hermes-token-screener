#!/usr/bin/env python3
"""Extract and normalize token contract addresses from text."""
import re
from typing import List, Tuple, Optional

# Regex patterns
EVM_PATTERN = re.compile(r'0x[a-fA-F0-9]{40}')
SOLANA_PATTERN = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')
DEX_LINK_PATTERN = re.compile(r'(?:dexscreener\.com|gmgn\.ai|raydium\.io|pump\.fun)/[^\s)]+')

# Known DEX link patterns -> extract token
DEXSCREENER_TOKEN_RE = re.compile(r'/tokens/([a-fA-F0-9]+)')
PUMP_FUN_RE = re.compile(r'/([a-fA-F0-9]+)')

def normalize_address(address: str) -> str:
    """Lowercase and clean."""
    return address.lower().strip()

def detect_chain(address: str) -> str:
    """Infer chain from address pattern."""
    if address.startswith('0x') and len(address) == 42:
        # Could be Ethereum, Base, BSC, etc. Default to 'ethereum' unless metadata says otherwise
        return 'ethereum'
    elif 32 <= len(address) <= 44 and all(c in '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz' for c in address):
        return 'solana'
    return 'unknown'

def extract_addresses(text: str) -> List[Tuple[str, str, str]]:
    """
    Extract token addresses from text.
    Returns list of (original, normalized_address, source_hint) tuples.
    """
    results = []
    text_lower = text.lower()

    # 1. Extract from DEX links FIRST (higher priority)
    for link_match in DEX_LINK_PATTERN.findall(text):
        full_link = link_match if isinstance(link_match, str) else link_match[0]
        if 'dexscreener.com' in full_link:
            # Extract EVM address directly from the link using regex
            token_match = EVM_PATTERN.search(full_link)
            if token_match:
                addr = token_match.group(0)
                results.append((full_link, normalize_address(addr), 'dexscreener_link'))
        elif 'gmgn.ai' in full_link:
            # GMGN links can be for Solana or EVM; try EVM first, then Solana
            evm_match = EVM_PATTERN.search(full_link)
            if evm_match:
                addr = evm_match.group(0)
                results.append((full_link, normalize_address(addr), 'gmgn_link'))
            else:
                sol_match = SOLANA_PATTERN.search(full_link)
                if sol_match:
                    addr = sol_match.group(0)
                    results.append((full_link, addr, 'gmgn_link'))
        elif 'pump.fun' in full_link:
            token_hash_match = PUMP_FUN_RE.search(full_link)
            if token_hash_match:
                addr = token_hash_match.group(1)
                results.append((full_link, addr, 'pump_fun_link'))

    # 2. Extract raw EVM addresses (lower priority to avoid double-counting)
    for match in EVM_PATTERN.findall(text):
        norm = normalize_address(match)
        # Check if already captured from a link
        if not any(norm == r[1] for r in results):
            results.append((match, norm, 'evm_raw'))

    # 3. Extract Solana addresses (base58)
    for match in SOLANA_PATTERN.findall(text):
        if len(match) >= 32:
            norm = match  # already base58
            if not any(norm == r[1] for r in results):
                results.append((match, norm, 'solana_raw'))

    # Deduplicate by normalized address (should already be unique)
    seen = set()
    unique = []
    for orig, norm, src in results:
        if norm not in seen:
            seen.add(norm)
            unique.append((orig, norm, src))

    return unique

def test_extractor():
    test_cases = [
        "Check out 0x18A8BD1fe17A1BB9FFB39eCD83E9489cfD17a022",
        "Dexscreener: https://dexscreener.com/base/0x18a8bd1fe17a1bb9ffb39ecd83e9489cfd17a022",
        "Pump: https://pump.fun/coin/AbcDef123...",
        "GMGN: https://gmgn.ai/sol/coin/AbcDef123...",
    ]
    for t in test_cases:
        print(f"Input: {t}")
        for r in extract_addresses(t):
            print(f"  → {r}")
        print()

if __name__ == '__main__':
    test_extractor()
