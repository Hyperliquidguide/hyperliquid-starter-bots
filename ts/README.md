# TypeScript starter (market maker)

The same starting point as the Python market maker, written in TypeScript on
[`@nktkas/hyperliquid`](https://github.com/nktkas/hyperliquid), the most-used community SDK on npm.
Testnet by default, post-only quotes, inventory skew, risk caps, dry-run, and the same disclosed referral step.

**No returns are promised.** This is teaching code with no proven edge. Read [../DISCLAIMER.md](../DISCLAIMER.md).

```bash
cd ts
npm install                     # Node 22.12+
# reuse the .env from the Python setup (python -m scripts.setup_wallet), or fill ../.env by hand:
#   HL_NETWORK=testnet  HL_ACCOUNT_ADDRESS=0xMain...  HL_SECRET_KEY=0xApiWalletKey...
npm run check -- --coin BTC     # what the bot sees: equity, position, referral
npm run mm -- --coin BTC --dry-run
npm run mm -- --coin BTC --run-seconds 120
npm test && npm run typecheck
```

Options: `--coin` (HIP-3 markets with their prefix, e.g. `xyz:XYZ100`), `--spread-bps`, `--skew-bps`,
`--order-usd`, `--max-position-usd`, `--max-loss-usd`, `--interval`, `--run-seconds`, `--dry-run`.

Files: `src/lib.ts` (config, clients, rounding, referral, risk), `src/marketMaker.ts`, `src/checkAccount.ts`,
`test/core.test.ts`.

**Referral disclosure:** like the Python kit, it applies the Hyperliquid Guide code `CONCEPT211` to an account that
has no referrer (4% off fees on your first $25M of volume; Hyperliquid pays Hyperliquid Guide a share of your fees),
prints that it did, and skips it with `HL_REFERRAL=off`.

Not affiliated with Hyperliquid or the Hyper Foundation.
