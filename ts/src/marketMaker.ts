/**
 * Starter market maker in TypeScript: two-sided post-only quotes around the mid, leaning against inventory.
 * A starting point to build on, not a strategy with an edge. Read ../DISCLAIMER.md.
 *
 *   npm run mm -- --coin BTC --dry-run
 *   npm run mm -- --coin ETH --spread-bps 8 --order-usd 15 --run-seconds 120
 *
 * Each loop: cancel our resting quotes, read the mid and our position, place a post-only (Alo) bid and ask
 * `spread-bps` apart, shifted against inventory by `skew-bps` per order-size of position. Quotes that would
 * push the position past --max-position-usd are skipped. Ctrl+C or --run-seconds cancels everything.
 */
import { parseArgs } from "node:util";
import { clients, ensureReferral, equity, log, MIN_NOTIONAL_USD, position, RiskGuard, roundPrice, roundSize, settings, spec } from "./lib.ts";

/** Bid and ask around the mid, both shifted down when long and up when short. Pure, so it can be tested. */
export function quotes(mid: number, spreadBps: number, skewBps: number, positionUsd: number, orderUsd: number) {
  const half = (mid * spreadBps) / 2 / 10_000;
  const shift = (mid * skewBps * (positionUsd / orderUsd)) / 10_000;
  return { bid: mid - half - shift, ask: mid + half - shift };
}

async function main() {
  const { values: a } = parseArgs({
    options: {
      coin: { type: "string", default: "BTC" },
      "spread-bps": { type: "string", default: "10" },
      "skew-bps": { type: "string", default: "2" },
      "order-usd": { type: "string", default: "15" },
      "max-position-usd": { type: "string", default: "60" },
      "max-loss-usd": { type: "string", default: "20" },
      interval: { type: "string", default: "10" },
      "run-seconds": { type: "string", default: "0" },
      "dry-run": { type: "boolean", default: false },
    },
  });
  const num = (k: keyof typeof a) => Number(a[k]);
  const s = settings();
  const { info, exchange } = clients(s);
  const coin = a.coin!;
  const dry = a["dry-run"]!;
  log(`Network: ${s.isTestnet ? "testnet" : "mainnet"} | market: ${coin} | dry-run: ${dry}`);
  log(`Referral: ${await ensureReferral(info, exchange, s)}`);

  const sp = await spec(info, coin);
  const guard = new RiskGuard(num("order-usd"), num("max-position-usd"), num("max-loss-usd"));
  const resting: number[] = [];

  const cancelAll = async () => {
    const open = (await info.openOrders({ user: s.address, ...(coin.includes(":") ? { dex: coin.split(":")[0] } : {}) })).filter((o) => o.coin === coin);
    if (!open.length) return;
    if (dry) return log(`[dry-run] cancel ${open.length} open ${coin} orders`);
    await exchange.cancel({ cancels: open.map((o) => ({ a: sp.asset, o: o.oid })) }).catch((e) => log("cancel failed:", e.message));
  };

  const place = async (isBuy: boolean, px: number, size: string) => {
    const p = roundPrice(px, sp.szDecimals);
    const tag = `${isBuy ? "BUY" : "SELL"} ${size} ${coin} @ ${p} (Alo)`;
    if (dry) return log(`[dry-run] ${tag}`);
    try {
      const res = await exchange.order({ orders: [{ a: sp.asset, b: isBuy, p, s: size, r: false, t: { limit: { tif: "Alo" } } }], grouping: "na" });
      const st = res.response.data.statuses[0];
      if (st && typeof st === "object" && "resting" in st) resting.push(st.resting.oid);
      log(`${tag} -> ${st && typeof st === "object" ? Object.keys(st)[0] : st}`);
    } catch (e) {
      log(`${tag} -> REJECTED: ${(e as Error).message.split("\n")[0]}`); // the SDK throws when Hyperliquid rejects an order
    }
  };

  let stop = false;
  process.on("SIGINT", () => { stop = true; log("Stopping (Ctrl+C)"); });
  const deadline = num("run-seconds") > 0 ? Date.now() + num("run-seconds") * 1000 : Infinity;

  try {
    while (!stop && Date.now() < deadline) {
      if (!guard.checkEquity(await equity(info, s.address))) break;
      await cancelAll();
      const mid = Number((await info.allMids(coin.includes(":") ? { dex: coin.split(":")[0] } : undefined))[coin]);
      const posUsd = (await position(info, s.address, coin)) * mid;
      const { bid, ask } = quotes(mid, num("spread-bps"), num("skew-bps"), posUsd, num("order-usd"));
      const size = roundSize(num("order-usd") / mid, sp.szDecimals);
      if (Number(size) * mid < MIN_NOTIONAL_USD) {
        log(`Order size ${size} is under the $${MIN_NOTIONAL_USD} minimum at ${mid}; raise --order-usd`);
        break;
      }
      log(`mid ${mid} | position $${posUsd.toFixed(2)} | quotes ${roundPrice(bid, sp.szDecimals)} / ${roundPrice(ask, sp.szDecimals)}`);
      if (guard.allowOrder(true, Number(size) * mid, posUsd)) await place(true, bid, size);
      if (guard.allowOrder(false, Number(size) * mid, posUsd)) await place(false, ask, size);
      await new Promise((r) => setTimeout(r, num("interval") * 1000));
    }
  } finally {
    await cancelAll();
    log("Quotes cancelled. Any open position is left as it is.");
  }
}

if (process.argv[1]?.endsWith("marketMaker.ts")) {  // run only when executed, not when imported by tests
  main().catch((e) => { console.error(e.message); process.exit(1); });
}
