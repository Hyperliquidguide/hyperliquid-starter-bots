# Hyperliquid Starter Bots

Small, readable Python trading bots for [Hyperliquid](https://app.hyperliquid.xyz/join/CONCEPT211), built on the official [hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk). Use them as a starting point, or point your coding agent (Claude Code, Codex, Cursor) at this repo and have it build your own strategy on top.

> **No returns are promised.** These bots are teaching code. They have no proven edge, and running them with real money can lose that money. Start on testnet. Read [DISCLAIMER.md](DISCLAIMER.md).

Maintained by [Hyperliquid Guide](https://hyperliquidguide.com), an independent site that isn't affiliated with Hyperliquid or the Hyper Foundation.

## What's inside

| Path | What it is |
|---|---|
| `bots/market_maker.py` | Posts a post-only bid and ask around the mid and leans the quotes against inventory |
| `bots/scalper.py` | EMA-crossover entries with exchange-side take-profit and stop-loss orders |
| `hlbots/client.py` | SDK wrapper: specs, prices, positions, equity, orders with correct rounding |
| `hlbots/specs.py` | Tick and lot size rounding, the cause of most rejected orders |
| `hlbots/risk.py` | Max order size, max position, and a daily loss kill switch |
| `hlbots/referral.py` | Referral setup (see [disclosure](#referral-disclosure)) |
| `scripts/setup_wallet.py` | Creates an API wallet and writes `.env` |
| `scripts/check_account.py` | Shows equity, position, fee rates and referral status |

## Quick start (testnet)

You need Python 3.10+ and a wallet that has made a deposit on Hyperliquid mainnet (the testnet faucet requires one).

```bash
git clone https://github.com/Hyperliquidguide/hyperliquid-starter-bots
cd hyperliquid-starter-bots
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. Get testnet USDC: https://app.hyperliquid-testnet.xyz/drip
# 2. Create an API wallet for the bots (asks for your main key, never saves it)
python -m scripts.setup_wallet

# 3. Check what the bot sees
python -m scripts.check_account --coin BTC

# 4. Watch a bot think without sending orders, then run it for real on testnet
python -m bots.market_maker --coin BTC --dry-run
python -m bots.market_maker --coin BTC
```

Every bot takes `--help`. HIP-3 markets use their dex prefix, for example `--coin xyz:XYZ100`.

## Going to mainnet

Run `python -m scripts.setup_wallet --mainnet`, deposit USDC, and keep the default small sizes until you have watched the bot through a few volatile hours. The bots read `HL_NETWORK` from `.env`, so nothing touches mainnet until you set it.

## Build your own strategy with a coding agent

This repo is laid out so a coding agent can extend it safely. [AGENTS.md](AGENTS.md) tells the agent the layout, the rules (rounding, risk checks, testnet first), and how to add a bot. Prompts that work:

- "Read AGENTS.md. Add a grid bot in `bots/grid.py` that places 10 levels between two prices, with tests."
- "Make the market maker widen its spread when 5-minute volatility rises. Add a test for the spread function."
- "Add a funding-rate filter to the scalper: only go long when funding is negative."

For Hyperliquid specifics (fees, rate limits, error messages, HIP-3 markets) the agent can read [hyperliquidguide.com/llms.txt](https://hyperliquidguide.com/llms.txt) and the [API guide](https://hyperliquidguide.com/guides/trading/hyperliquid-api-guide).

## Safety

- **Use an API wallet.** It can trade but can't withdraw. `setup_wallet` creates one, and the bots warn if you give them your main key.
- **Keys stay local.** `.env` is gitignored. Never paste a key into a chat, an issue or a commit.
- **Risk limits are on by default.** They're a floor. Tighten them before you size up.
- **Trigger orders live on the exchange.** The scalper's stop-loss still fires if your machine dies. The market maker cancels its quotes on exit.

## Referral disclosure

If your account has no referrer yet and has traded less than about $10K, `setup_wallet` and the bots apply the Hyperliquid Guide referral code `CONCEPT211`. Under Hyperliquid's referral program you get **4% off trading fees on your first $25M of volume**, and Hyperliquid pays Hyperliquid Guide a share of the fees you pay. You pay less, not more. The code is never applied over an existing referrer, and it's skipped on testnet.

To opt out, set `HL_REFERRAL=off` in `.env`. To use a different code, set `HL_REFERRAL_CODE`.

## Tests

```bash
python -m pytest
```

The tests run offline with no keys.

## License

MIT. See [LICENSE](LICENSE).
