/**
 * Shared helpers for the TypeScript starter: config, clients, rounding, referral, risk.
 * Same rules and defaults as the Python kit in ../hlbots. Testnet unless HL_NETWORK=mainnet.
 */
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { ExchangeClient, HttpTransport, InfoClient } from "@nktkas/hyperliquid";
import { privateKeyToAccount } from "viem/accounts";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const ENV = path.join(ROOT, ".env");
if (existsSync(ENV)) process.loadEnvFile(ENV); // shares .env with the Python bots

export const REFERRAL_CODE = process.env.HL_REFERRAL_CODE ?? "CONCEPT211";
export const MIN_NOTIONAL_USD = 10;
const REFERRAL_VOLUME_CUTOFF = 10_000;

export const log = (...a: unknown[]) => console.log(new Date().toISOString().slice(11, 19), ...a);

// ---------- config + clients ----------

export function settings() {
  const network = (process.env.HL_NETWORK ?? "testnet").toLowerCase();
  const address = process.env.HL_ACCOUNT_ADDRESS as `0x${string}` | undefined;
  const key = process.env.HL_SECRET_KEY as `0x${string}` | undefined;
  if (!address || !key) {
    throw new Error("Set HL_ACCOUNT_ADDRESS and HL_SECRET_KEY in ../.env (python -m scripts.setup_wallet writes them).");
  }
  return { isTestnet: network !== "mainnet", address, key, referral: (process.env.HL_REFERRAL ?? "on") !== "off" };
}

export function clients(s: ReturnType<typeof settings>) {
  const transport = new HttpTransport({ isTestnet: s.isTestnet });
  const wallet = privateKeyToAccount(s.key);
  if (wallet.address.toLowerCase() === s.address.toLowerCase()) {
    log("WARNING: HL_SECRET_KEY is your main wallet key. Prefer an API wallet: it can trade but cannot withdraw.");
  }
  // An API (agent) wallet signs; Hyperliquid maps it to the main account it was approved for.
  return { info: new InfoClient({ transport }), exchange: new ExchangeClient({ transport, wallet }) };
}

// ---------- market specs + rounding ----------

export type Spec = { coin: string; asset: number; szDecimals: number; maxLeverage: number };

/** Asset id and size decimals. HIP-3 names carry their dex prefix (xyz:XYZ100): id = 100000 + dexIdx * 10000 + idx. */
export async function spec(info: InfoClient, coin: string): Promise<Spec> {
  const dex = coin.includes(":") ? coin.split(":")[0] : "";
  const meta = await info.meta(dex ? { dex } : undefined);
  const idx = meta.universe.findIndex((u) => u.name === coin);
  if (idx < 0) throw new Error(`Unknown market ${coin}. HIP-3 markets need their prefix, e.g. xyz:XYZ100.`);
  let asset = idx;
  if (dex) {
    const dexes = await info.perpDexs();
    const dexIdx = dexes.findIndex((d) => d?.name === dex);
    asset = 100_000 + dexIdx * 10_000 + idx;
  }
  const u = meta.universe[idx];
  return { coin, asset, szDecimals: u.szDecimals, maxLeverage: u.maxLeverage };
}

/** Round DOWN to the lot size, so we never send more than intended. */
export function roundSize(size: number, szDecimals: number): string {
  const f = 10 ** szDecimals;
  return (Math.floor(Math.abs(size) * f + 1e-9) / f).toFixed(szDecimals);
}

/** Perp prices: at most 5 significant figures and 6 - szDecimals decimals. Integers are always valid. */
export function roundPrice(px: number, szDecimals: number, isSpot = false): string {
  if (px <= 0) throw new Error(`price must be positive, got ${px}`);
  if (px >= 1e5 && Number.isInteger(px)) return String(px);
  const maxDec = Math.max((isSpot ? 8 : 6) - szDecimals, 0);
  return String(Number(Number(px.toPrecision(5)).toFixed(maxDec)));
}

// ---------- referral (disclosed; HL_REFERRAL=off skips it) ----------

export const DISCLOSURE =
  `Referral: this starter kit applies the Hyperliquid Guide referral code (${REFERRAL_CODE}) to accounts that ` +
  "have none. Hyperliquid gives you 4% off fees on your first $25M of volume and pays Hyperliquid Guide a share " +
  "of your fees. Set HL_REFERRAL=off to skip.";

export async function ensureReferral(info: InfoClient, exchange: ExchangeClient, s: ReturnType<typeof settings>): Promise<string> {
  if (!s.referral) return "skipped (HL_REFERRAL=off)";
  try {
    const state = await info.referral({ user: s.address });
    const by = state.referredBy?.code;
    if (state.referredBy) return by && by !== "N/A" ? `already set (${by})` : "not available (past Hyperliquid's referral window)";
    if (Number(state.cumVlm) >= REFERRAL_VOLUME_CUTOFF) return "not available (account is past the ~$10K referral window)";
    if (s.isTestnet && REFERRAL_CODE === "CONCEPT211") return "skipped on testnet (the code only exists on mainnet)";
    log(DISCLOSURE);
    await exchange.setReferrer({ code: REFERRAL_CODE });
    await new Promise((r) => setTimeout(r, 1500));
    const after = await info.referral({ user: s.address }); // "ok" is not proof: re-read the state
    return after.referredBy?.code === REFERRAL_CODE ? `applied (${REFERRAL_CODE})` : `not applied (${after.referredBy?.code ?? "none"})`;
  } catch (e) {
    return `not applied (${(e as Error).message.split("\n")[0]})`; // a referral problem never stops a bot
  }
}

// ---------- account ----------

export async function position(info: InfoClient, user: string, coin: string): Promise<number> {
  const dex = coin.includes(":") ? coin.split(":")[0] : undefined;
  const st = await info.clearinghouseState(dex ? { user, dex } : { user });
  const p = st.assetPositions.find((a) => a.position.coin === coin);
  return p ? Number(p.position.szi) : 0;
}

/** Perp account value plus spot USDC: unified accounts keep collateral in spot. */
export async function equity(info: InfoClient, user: string): Promise<number> {
  const [perp, spot] = await Promise.all([info.clearinghouseState({ user }), info.spotClearinghouseState({ user })]);
  const usdc = spot.balances.find((b) => b.coin === "USDC");
  return Number(perp.marginSummary.accountValue) + Number(usdc?.total ?? 0);
}

// ---------- risk ----------

export class RiskGuard {
  private start?: number;
  halted = false;
  constructor(readonly maxOrderUsd: number, readonly maxPositionUsd: number, readonly maxLossUsd: number) {}

  checkEquity(eq: number): boolean {
    this.start ??= eq;
    if (this.start - eq >= this.maxLossUsd) {
      if (!this.halted) log(`HALT: loss $${(this.start - eq).toFixed(2)} reached the $${this.maxLossUsd} limit`);
      this.halted = true;
    }
    return !this.halted;
  }

  /** positionUsd is signed: positive long, negative short. Orders that shrink the position are always allowed. */
  allowOrder(isBuy: boolean, notionalUsd: number, positionUsd: number): boolean {
    if (this.halted || notionalUsd > this.maxOrderUsd + 1e-9) return false;
    const after = positionUsd + (isBuy ? notionalUsd : -notionalUsd);
    return !(Math.abs(after) > this.maxPositionUsd + 1e-9 && Math.abs(after) > Math.abs(positionUsd));
  }
}
