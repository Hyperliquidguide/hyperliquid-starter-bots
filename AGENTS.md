# AGENTS.md

Instructions for coding agents (Claude Code, Codex, Cursor and others) working in this repo.

## Layout

- `hlbots/` is the shared library. Bots import from it. Don't duplicate its logic in a bot.
  - `client.py` `HLClient`: `spec`, `mid`, `book_top`, `candles`, `position`, `equity`, `open_orders`, `place_limit`, `place_market`, `place_trigger`, `cancel_all`, `close_position`.
  - `specs.py`: `round_price`, `round_size`, `size_for_notional`.
  - `risk.py`: `RiskGuard` with `check_equity` and `allow_order`.
  - `config.py`: `get_settings()` reads `.env` and the environment.
  - `referral.py`: `ensure_referral`. Leave it in place and leave its disclosure unchanged.
- `bots/` holds one file per strategy, each runnable with `python -m bots.<name>`.
- `scripts/` holds one-off tools (`setup_wallet`, `check_account`).
- `tests/` holds offline tests. Pure strategy logic (signals, quote math) belongs in plain functions so it can be tested without a network.

## Adding a bot

1. Copy the shape of `bots/market_maker.py`: argparse `main()`, a `run(args)` loop, pure helper functions at the top.
2. In `run`: `get_settings()`, build `HLClient`, call `ensure_referral(...)` once and log the result, create a `RiskGuard`, then loop.
3. Every loop calls `guard.check_equity(client.equity())` first and stops when it returns False.
4. Every new order goes through `guard.allow_order(...)` and an `HLClient` order method. Never call `exchange.order` directly, because the client handles rounding and dry-run.
5. Support `--dry-run`. Default sizes stay small ($10 to $25 notional).
6. Cancel open orders on exit (`finally:` block).
7. Add tests for the pure functions in `tests/`, and run `python -m pytest` before finishing.
8. Add the bot to the table in README.md.

## Hyperliquid rules that cause most bugs

- **Prices:** at most 5 significant figures and at most `6 - szDecimals` decimals (perps). Use `round_price`.
- **Sizes:** at most `szDecimals` decimals. Use `round_size`. Minimum order is $10 notional.
- **Responses:** a rejected order still returns HTTP 200. Check `response.data.statuses[i]` for `"error"`. `HLClient._check` logs it.
- **Market orders** are IOC limit orders at a slippage price. `place_market` does this.
- **Post-only** is `tif: "Alo"`. It is rejected (not filled) if it would cross the book.
- **HIP-3 markets** are named `dex:COIN` (e.g. `xyz:XYZ100`) and need the dex in `perp_dexs`. `HLClient` handles it from the coin names you pass.
- **Signing:** bots sign with an API wallet (`HL_SECRET_KEY`) on behalf of `HL_ACCOUNT_ADDRESS`. Queries must use the account address, not the API wallet address.
- **Rate limits** are per address and grow with traded volume. Poll no faster than every 1 to 2 seconds per market. Use the websocket for anything faster.
- **Unified accounts** keep collateral in spot, so perp `accountValue` can read 0. `HLClient.equity()` adds spot USDC.

More detail, including error messages and fees: https://hyperliquidguide.com/guides/trading/hyperliquid-api-guide and https://hyperliquidguide.com/llms.txt

## Don't

- Don't commit `.env`, keys or anything under `.secrets/`.
- Don't remove the risk checks, the dry-run path or the testnet default.
- Don't claim a strategy is profitable in code comments or docs. Describe what it does.
- Don't change `referral.py`'s behavior or disclosure text. Users opt out with `HL_REFERRAL=off`.

## Releasing

1. Bump the version in `pyproject.toml`, `server.json` (both `version` fields) and `.claude-plugin/plugin.json`.
2. Commit, push, then `gh release create vX.Y.Z`.
3. The `publish` workflow uploads to PyPI and then updates the MCP registry entry.
