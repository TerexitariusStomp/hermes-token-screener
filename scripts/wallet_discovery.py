#!/usr/bin/env python3
"""Discover and rank smart-money wallets from enriched token data."""
from typing import List, Dict, Any
from smart_money_config import MIN_TRADES_PER_TOKEN, MIN_WIN_RATE, MIN_REALIZED_PNL

def discover_smart_wallets(dexscreener_data: Dict[str, Any], gmgn_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Combine Dexscreener and GMGN data to produce a ranked list of candidate smart wallets.
    Filters: min trades >= threshold, win_rate >= threshold, positive PnL.
    """
    smart_wallets = gmgn_data.get('smart_wallets', [])
    if not smart_wallets:
        return []

    candidate_wallets = []
    for wallet in smart_wallets:
        trades = wallet.get('trade_count', 0)
        win_rate = wallet.get('win_rate', 0)
        pnl = wallet.get('realized_pnl', 0)

        if trades >= MIN_TRADES_PER_TOKEN and win_rate >= MIN_WIN_RATE and pnl > MIN_REALIZED_PNL:
            # Add token context to wallet for downstream aggregation
            wallet['token_address'] = gmgn_data.get('token_address')
            wallet['token_chain'] = gmgn_data.get('chain')
            wallet['token_fdv'] = dexscreener_data.get('fdv_usd') if dexscreener_data else None
            candidate_wallets.append(wallet)

    # Sort by: primary realized_pnl (desc), secondary win_rate, tertiary trade_count
    ranked = sorted(
        candidate_wallets,
        key=lambda w: (w['realized_pnl'], w['win_rate'], w['trade_count']),
        reverse=True
    )

    # Return top 5
    top_wallets = ranked[:5]
    print(f"[WalletDiscovery] Found {len(top_wallets)} top smart wallets for token {gmgn_data.get('token_address')[:10]}...")
    return top_wallets

def test_discovery():
    # Mock data suite
    dex = {
        'fdv_usd': 2500000,
        'liquidity_usd': 150000
    }
    gmgn = {
        'token_address': '0x18A8BD1fe17A1BB9FFB39eCD83E9489cfD17a022',
        'chain': 'base',
        'smart_wallets': [
            {'address': '0xw1', 'realized_pnl': 50000, 'win_rate': 0.85, 'trade_count': 12, 'avg_hold_hours': 3.2, 'insider_flag': True},
            {'address': '0xw2', 'realized_pnl': 20000, 'win_rate': 0.90, 'trade_count': 8, 'avg_hold_hours': 2.1, 'insider_flag': False},
            {'address': '0xw3', 'realized_pnl': 15000, 'win_rate': 0.55, 'trade_count': 20, 'avg_hold_hours': 1.5, 'insider_flag': False},  # filtered (win_rate too low)
            {'address': '0xw4', 'realized_pnl': 85000, 'win_rate': 0.92, 'trade_count': 25, 'avg_hold_hours': 4.8, 'insider_flag': True},
        ]
    }
    top = discover_smart_wallets(dex, gmgn)
    print("Top wallets:")
    for w in top:
        print(f"  {w['address']} - PnL: ${w['realized_pnl']:,}, WR: {w['win_rate']*100:.0f}%, trades: {w['trade_count']}")

if __name__ == '__main__':
    test_discovery()
