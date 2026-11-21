# hyperliquid-guide MCP server

Read-only Hyperliquid reference tools for coding agents. Holds no keys, places no orders.

| Tool | What it returns |
|---|---|
| `market_specs(coin)` | szDecimals, max price decimals, max leverage, mark/mid, hourly funding + APR, OI, growth mode |
| `round_order(coin, price, size)` | A valid price and size, plus the $10 minimum check |
| `top_funding(limit, dex)` | Markets ranked by funding APR |
| `explain_error(message)` | Cause and fix for a Hyperliquid rejection |
| `account_status(address)` | Equity, positions, fee rates, referral status and whether a code can still be added |
| `quickstart()` | The agent quickstart (endpoints, rounding, errors, fees, rate limits) |
| `starter_bot(kind)` | Source of `market_maker`, `scalper`, `grid` or `funding_arb` |

Install commands for Claude Code, Codex, Cursor and Claude Desktop are in the main [README](../README.md#use-it-from-your-coding-agent).
