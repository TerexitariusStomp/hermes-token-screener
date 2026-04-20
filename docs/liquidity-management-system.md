# Liquidity Management System (Zero-Idle Objective)

This module adds a deterministic liquidity planner + daemon that aims to keep every deployable token generating LP fees.

Implemented files:
- `hermes_screener/trading/liquidity_manager.py`
- `hermes_screener/trading/liquidity_daemon.py`
- `hermes_screener/trading/portfolio_registry.py`
- `hermes_screener/trading/price_oracle.py`
- `hermes_screener/trading/protocol_liquidity_executor.py`
- `scripts/liquidity_daemon.py`
- `scripts/liquidity_registry.py`
- `scripts/liquidity_targets.py`
- tests: `tests/test_liquidity_manager.py`, `tests/test_liquidity_daemon.py`, `tests/test_portfolio_registry.py`, `tests/test_price_oracle.py`, `tests/test_protocol_liquidity_executor.py`

## Core behavior

1. Collect balances and reserve gas buffers.
2. Load tracked tokens registry (all assets you trade).
3. Fetch prices by token address (Coingecko + cache fallback).
4. Build opportunities for tracked assets (Arrakis/Gamma on Base, Kamino on Solana).
5. Deploy in this order:
   - dual-sided LP (Arrakis/Gamma style)
   - single-sided LP (Kamino style)
   - single-asset vault
6. Force-sweep residual balances:
   - try single-sided routes for each token
   - otherwise try dual-pair forced balancing swap + deposit
7. If any non-dust balance still has no deployment route, raise `NoDeploymentPathError`.

This hard-fail behavior enforces the zero-idle invariant at planner level.

## Phase 2 additions

- Portfolio token registry so liquidity management covers any token you trade.
- Multi-token balance ingestion:
  - Base native + ERC20 balances from tracked registry
  - Solana native + SPL balances from tracked registry
- Price oracle by token address with local cache.
- Real swap execution path for balancing actions:
  - Base: executes via `ContractExecutor.smart_swap` (on-chain + aggregator tx routes)
  - Solana: executes via `SolanaProgramAdapter.swap`
- Registry CLI to add/remove/list managed tokens.

## Phase 3 additions (protocol-native deploy execution)

- New protocol deploy executor:
  - `ProtocolLiquidityExecutor` in `hermes_screener/trading/protocol_liquidity_executor.py`
- New target-mapping CLI:
  - `scripts/liquidity_targets.py`
- New daemon flag:
  - `--live-deploy` (turns on actual protocol tx execution)

Deploy behavior:
- Arrakis (Base):
  - Reads `vault` + `resolver` target config
  - Approves token0/token1
  - Calls resolver `getMintAmounts(...)`
  - Sends `vault.mint(mintAmount, receiver)` transaction
- Gamma (Base):
  - Reads `manager` + token order config
  - Approves token0/token1
  - Sends `manager.deposit(deposit0Desired, deposit1Desired, to, from)`
- Kamino (Solana):
  - Reads `strategy` target config
  - Executes via external command hook if provided (`KAMINO_DEPOSIT_CMD`)
  - Falls back to dry-run log if hook not configured

## Manage tracked tokens

List:
`python3 scripts/liquidity_registry.py list`

Add token:
`python3 scripts/liquidity_registry.py add --symbol BONK --chain solana --address DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --decimals 5`

Remove token:
`python3 scripts/liquidity_registry.py remove --chain solana --address DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263`

## Manage protocol targets

List targets:
`python3 scripts/liquidity_targets.py list`

Add Arrakis target:
`python3 scripts/liquidity_targets.py add-arrakis --id arrakis-base-weth-usdc --vault <VAULT_ADDR> --resolver <RESOLVER_ADDR>`

Add Gamma target:
`python3 scripts/liquidity_targets.py add-gamma --id gamma-base-weth-usdc --manager <MANAGER_ADDR> --token0-symbol WETH --token1-symbol USDC`

Add Kamino target:
`python3 scripts/liquidity_targets.py add-kamino --id kamino-sol-usdc --strategy <STRATEGY_PUBKEY> --slippage-bps 50`

Remove target:
`python3 scripts/liquidity_targets.py remove --id <TARGET_ID>`

## Run one cycle

Dry-run deploy legs (safe):
`python3 scripts/liquidity_daemon.py --once`

Live protocol deploy mode:
`python3 scripts/liquidity_daemon.py --once --live-deploy`

## Run continuously

Dry-run:
`python3 scripts/liquidity_daemon.py --loop-seconds 300`

Live:
`python3 scripts/liquidity_daemon.py --loop-seconds 300 --live-deploy`

## Notes before scaling capital

- Configure accurate `liquidity_targets` for every opportunity id you intend to execute.
- Keep `--live-deploy` off until targets and wallet permissions are verified.
- Kamino live execution requires a configured external executor command via `KAMINO_DEPOSIT_CMD`.
- Add per-token notional caps and kill-switch policy before high-notional deployment.

## Test status

Targeted tests pass:

`python3 -m pytest -q tests/test_liquidity_manager.py tests/test_liquidity_daemon.py tests/test_portfolio_registry.py tests/test_price_oracle.py tests/test_protocol_liquidity_executor.py`
