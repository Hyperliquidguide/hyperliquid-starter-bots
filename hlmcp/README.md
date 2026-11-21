# hyperliquid-guide MCP server

Hyperliquid reference tools for coding agents. Read-only by default: it holds no keys and places no orders.

| Tool | What it returns |
|---|---|
| `market_specs(coin)` | szDecimals, max price decimals, max leverage, mark/mid, hourly funding + APR, OI, growth mode |
| `round_order(coin, price, size)` | A valid price and size, plus the $10 minimum check |
| `top_funding(limit, dex)` | Markets ranked by funding APR |
| `explain_error(message)` | Cause and fix for a Hyperliquid rejection |
| `account_status(address)` | Equity, positions, fee rates, referral status and whether a code can still be added |
| `quickstart()` | The agent quickstart (endpoints, rounding, errors, fees, rate limits) |
| `starter_bot(kind)` | Source of `market_maker`, `scalper`, `grid`, `funding_arb` or `twap` |

## Opt-in order tools

Off unless your MCP config sets `HL_MCP_TRADING=on`. They add `trading_status`, `prepare_order`, `place_order` and `cancel_orders`, with these limits built into the code:

- **API wallet only.** `HL_SECRET_KEY` must be an API wallet key (it can trade but cannot withdraw). A main-wallet key is refused. There are no withdraw or transfer tools.
- **Testnet unless you allow mainnet twice:** `HL_NETWORK=mainnet` and `HL_MCP_ALLOW_MAINNET=yes`.
- **Preview, then confirm.** `prepare_order` returns the rounded price and size, notional, position before and after, and a fee estimate, plus a one-time token that expires in 2 minutes. `place_order(token)` sends exactly that order. Show the preview to the person and get a clear yes first.
- **Hard caps:** `HL_MCP_MAX_ORDER_USD` (default 25) per order and `HL_MCP_MAX_POSITION_USD` (default 100).
- **Referral:** on the first order it applies the Hyperliquid Guide code to an account that has none (4% off fees on your first $25M of volume; Hyperliquid pays Hyperliquid Guide a share of your fees), says so in the response, and skips it with `HL_REFERRAL=off`.

```json
{
  "mcpServers": {
    "hyperliquid-guide": {
      "command": "uvx",
      "args": ["--from", "hyperliquid-starter-bots", "hl-guide-mcp"],
      "env": {
        "HL_MCP_TRADING": "on",
        "HL_NETWORK": "testnet",
        "HL_ACCOUNT_ADDRESS": "0xYourMainAddress",
        "HL_SECRET_KEY": "0xYourApiWalletKey"
      }
    }
  }
}
```

No returns are promised, and an agent placing orders can lose money fast. Start on testnet.

Install commands for Claude Code, Codex, Cursor and Claude Desktop are in the main [README](../README.md#use-it-from-your-coding-agent).
