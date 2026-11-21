/** Print what the bot will see: network, equity, position, open orders, referral. `npm run check -- --coin BTC` */
import { parseArgs } from "node:util";
import { clients, equity, position, settings, spec } from "./lib.ts";

const { values } = parseArgs({ options: { coin: { type: "string", default: "BTC" } } });
const coin = values.coin!;
const s = settings();
const { info } = clients(s);
const dex = coin.includes(":") ? coin.split(":")[0] : undefined;
const [sp, eq, pos, open, ref, mids] = await Promise.all([
  spec(info, coin), equity(info, s.address), position(info, s.address, coin),
  info.openOrders(dex ? { user: s.address, dex } : { user: s.address }), info.referral({ user: s.address }),
  info.allMids(dex ? { dex } : undefined),
]);
const rows: [string, string][] = [
  ["network", s.isTestnet ? "testnet" : "mainnet"],
  ["account", s.address],
  ["equity", `$${eq.toFixed(2)}`],
  [coin, `mid ${mids[coin]} | asset ${sp.asset} | szDecimals ${sp.szDecimals} | max leverage ${sp.maxLeverage}x`],
  ["position", String(pos)],
  ["open orders", String(open.filter((o) => o.coin === coin).length)],
  ["referral", ref.referredBy?.code ?? "none"],
];
for (const [k, v] of rows) console.log(k.padEnd(16), v);
