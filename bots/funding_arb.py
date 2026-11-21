"""Starter funding-rate capture: hold spot, short the same size on the perp, collect funding while it is positive.

This is a starting point to build on, not a strategy with an edge. Read DISCLAIMER.md.

    python -m bots.funding_arb --coin BTC --dry-run
    python -m bots.funding_arb --coin ETH --min-apr 20 --exit-apr 5 --order-usd 20

What it does: when longs pay shorts (positive funding), a short perp position earns the funding
payment. Buying the same size of the spot token cancels the price exposure, so what is left is
roughly the funding payment minus trading fees and any basis move. The bot opens that pair when
the annualized funding is high enough and closes both legs when it falls too low.

How it works, step by step:
1. Funding comes from client.info.meta_and_asset_ctxs(). The asset context field "funding" is the
   current hourly rate. Hyperliquid pays funding every hour, so the annualized rate is
   hourly_to_apr(rate) = rate * 24 * 365.
2. Find the spot market for the perp's base token with find_spot_pair() (mapping below). If the
   perp has no spot counterpart, the bot exits with a clear message.
3. Each loop: check equity against the daily loss limit, read the funding APR, and read both legs
   from the account (perp position and spot token balance), so a restart picks up where it left off.
4. Flat and should_enter(apr >= --min-apr): buy spot first (IOC at a small slippage). If the spot
   buy does not fill, nothing else is sent and the reason is logged. Only after the spot fills, short
   the same size on the perp. If the perp short fails, the spot is sold back.
5. Hedged and should_exit(apr < --exit-apr): sell the spot and buy back the perp (reduce-only
   close). Keeping --exit-apr below --min-apr avoids flip-flopping around one threshold.
6. On exit all open orders are cancelled. Open positions are left as they are, because closing
   them is a decision about funding, not a clean-up step.

Spot and perp naming: the perp is named by its base ("BTC"). The matching spot token is often
that name with a "U" prefix, because spot tokens bridged from other chains are wrapped ("UBTC",
"UETH", "USOL"), while HYPE and a few others keep the plain name. info.spot_meta() returns
`tokens` (name, index, szDecimals) and `universe` (pairs: name plus [base index, quote index]).
find_spot_pair() tries the candidate token names, keeps the pair quoted in USDC (token index 0),
and prefers the canonical pair. The pair name is "PURR/USDC" for the first pair and "@<index>" for
all others, and that name is what the SDK takes as `coin` for orders and prices.

Account type matters: on a standard account spot and perp balances are separate, so the spot buy
needs USDC in the spot balance (move it with the exchange's usd_class_transfer or use a unified
account) and the perp short needs perp margin. The bot checks the spot USDC balance first and logs
"spot leg cannot fill" if it is short, instead of sending an order that would be rejected.

Risks that are not funding: the spot and perp prices can drift apart (basis), funding can turn
negative and cost you, fees apply to both legs on entry and exit, and the perp can be liquidated if
the price rises a lot while margin is thin.

Ideas to build on: use predictedFundings (the next hour's estimate) or an average of recent
fundingHistory instead of the current rate, include fees in the entry test, rebalance the hedge when
the legs drift apart, post-only entries to pay maker fees, scan every perp and pick the best, set
isolated margin and a lower leverage on the perp leg.
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any

from hlbots import setup_logging
from hlbots.client import HLClient
from hlbots.config import get_settings
from hlbots.referral import ensure_referral
from hlbots.risk import RiskGuard, RiskLimits
from hlbots.specs import AssetSpec, round_size, size_for_notional

log = logging.getLogger("funding_arb")

HOURS_PER_YEAR = 24 * 365
SPOT_SLIPPAGE = 0.01  # IOC limit distance from mid on both legs, 1%
HEDGE_TOLERANCE = 0.9  # spot held must be at least this share of the short to count as hedged


def hourly_to_apr(hourly_rate: float) -> float:
    """Hyperliquid funding is paid hourly, so APR (as a fraction, 0.1095 = 10.95%) = hourly * 24 * 365."""
    return hourly_rate * HOURS_PER_YEAR


def should_enter(apr: float, min_apr: float, hedged: bool) -> bool:
    """Open the pair only when flat and funding is at or above the entry threshold."""
    return not hedged and apr >= min_apr


def should_exit(apr: float, exit_apr: float, hedged: bool) -> bool:
    """Close the pair when hedged and funding has fallen below the exit threshold."""
    return hedged and apr < exit_apr


def find_spot_pair(spot_meta: dict[str, Any], perp_base: str) -> tuple[str, str] | None:
    """Map a perp base name to (spot pair name, spot token name), or None if there is no USDC pair.

    Tries the plain token name first and then the "U"-prefixed wrapped name (BTC -> UBTC).
    Among USDC-quoted pairs for a candidate it prefers the canonical one, then the lowest index."""
    tokens = spot_meta["tokens"]
    for candidate in (perp_base, "U" + perp_base):
        token_ids = {t["index"] for t in tokens if t["name"].strip() == candidate}
        pairs = [
            m for m in spot_meta["universe"]
            if m["tokens"][0] in token_ids and m["tokens"][1] == 0  # token 0 is USDC
        ]
        if pairs:
            best = min(pairs, key=lambda m: (not m.get("isCanonical", False), m["index"]))
            return best["name"], candidate
    return None


def hedge_size(notional_usd: float, price: float, spot: AssetSpec, perp: AssetSpec) -> float:
    """Size both legs can trade: the coarser of the two lot sizes, so the legs match exactly."""
    coarse = AssetSpec(perp.coin, min(spot.sz_decimals, perp.sz_decimals), perp.max_leverage)
    return size_for_notional(notional_usd, price, coarse)


def funding_rate(meta_and_ctxs: list[Any], coin: str) -> float | None:
    """Current hourly funding for `coin` from a meta_and_asset_ctxs() response, or None if not listed."""
    meta, ctxs = meta_and_ctxs
    for asset, ctx in zip(meta["universe"], ctxs):
        if asset["name"] == coin:
            return float(ctx["funding"])
    return None


def run(args: argparse.Namespace) -> None:
    if ":" in args.coin:
        raise SystemExit("funding_arb needs a native perp with a spot token, e.g. BTC, ETH, HYPE. HIP-3 markets have no spot leg.")
    settings = get_settings()
    client = HLClient(settings, [args.coin], dry_run=args.dry_run)
    log.info("Network: %s | market: %s | dry-run: %s", settings.network, args.coin, args.dry_run)
    log.info("Referral: %s", ensure_referral(client.exchange, client.info, client.address, settings.referral_code, settings.referral_enabled, settings.is_mainnet))

    pair = find_spot_pair(client.info.spot_meta(), args.coin)
    if pair is None:
        raise SystemExit(f"No USDC spot pair found for {args.coin} (tried {args.coin} and U{args.coin}) on {settings.network}.")
    spot_name, token = pair
    perp_spec, spot_spec = client.spec(args.coin), client.spec(spot_name)
    log.info("Spot leg: %s (token %s, %d size decimals) | perp leg: %s (%d size decimals)", spot_name, token, spot_spec.sz_decimals, args.coin, perp_spec.sz_decimals)

    # Both legs are sized from order_usd; the guard limit leaves room for rounding and slippage.
    guard = RiskGuard(RiskLimits(args.order_usd * 1.25, args.order_usd * 1.25, args.max_loss_usd))
    paper_hedged = False  # dry-run only: orders are not sent, so remember the pretend position

    deadline = time.time() + args.run_seconds if args.run_seconds else None
    try:
        while deadline is None or time.time() < deadline:
            if not guard.check_equity(client.equity()):
                break
            rate = funding_rate(client.info.meta_and_asset_ctxs(), args.coin)
            if rate is None:
                raise SystemExit(f"{args.coin} not found in the perp universe.")
            apr = hourly_to_apr(rate)

            perp_size, _ = client.position(args.coin)
            spot_held = client.spot_balance(token)
            hedged = (perp_size < 0 and spot_held >= abs(perp_size) * HEDGE_TOLERANCE) or paper_hedged
            log.info("funding %.6f%%/h = %.2f%% APR | perp %s | spot %s %s | %s", rate * 100, apr * 100, perp_size, spot_held, token, "hedged" if hedged else "flat")

            if should_enter(apr, args.min_apr / 100, hedged):
                paper_hedged = enter(client, guard, args, spot_name, token, perp_spec, spot_spec) and args.dry_run
            elif should_exit(apr, args.exit_apr / 100, hedged):
                log.info("EXIT: funding %.2f%% APR is under --exit-apr %.2f%%", apr * 100, args.exit_apr)
                if args.dry_run:
                    log.info("[dry-run] would sell the spot %s and close the %s short", token, args.coin)
                else:
                    size = round_size(min(spot_held, abs(perp_size)), spot_spec)
                    if size > 0:
                        client.place_market(spot_name, False, size, SPOT_SLIPPAGE)
                    client.close_position(args.coin)
                paper_hedged = False
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Stopping (Ctrl+C)")
    finally:
        client.cancel_all(args.coin)
        client.cancel_all(spot_name)
        log.info("Open orders cancelled. Positions left as they are.")


def enter(client: HLClient, guard: RiskGuard, args: argparse.Namespace, spot_name: str, token: str, perp_spec: AssetSpec, spot_spec: AssetSpec) -> bool:
    """Open the pair: spot buy first, perp short only after the spot filled. Returns True if both legs went out."""
    coin = args.coin
    mid = client.mid(spot_name)
    qty = hedge_size(args.order_usd, mid * (1 + SPOT_SLIPPAGE), spot_spec, perp_spec)
    if not qty:
        log.warning("ENTRY skipped: order size rounds to zero (order-usd %.2f, price %.6g)", args.order_usd, mid)
        return False
    notional = qty * mid
    if notional > args.order_usd * 1.25:
        log.warning(
            "ENTRY skipped: the smallest tradable hedge is %s %s (about $%.2f), far above --order-usd %.2f. "
            "The spot token's lot size is too coarse for this order size.",
            qty, token, notional, args.order_usd,
        )
        return False
    usdc = client.spot_balance("USDC")
    if not client.dry_run and usdc < notional * (1 + SPOT_SLIPPAGE):
        log.warning(
            "ENTRY skipped: spot leg cannot fill. Spot USDC is $%.2f but the buy needs about $%.2f. "
            "Standard accounts keep spot and perp balances apart: move USDC to spot or use a unified account.",
            usdc, notional * (1 + SPOT_SLIPPAGE),
        )
        return False
    if not guard.allow_order(True, notional, 0.0) or not guard.allow_order(False, notional, 0.0):
        return False

    log.info("ENTRY: buy %s %s on spot, then short the same size on %s", qty, token, coin)
    before = client.spot_balance(token)
    client.place_market(spot_name, True, qty, SPOT_SLIPPAGE)
    if client.dry_run:
        client.place_market(coin, False, qty, SPOT_SLIPPAGE)
        return True
    time.sleep(1)
    got = round_size(client.spot_balance(token) - before, perp_spec)
    if got <= 0:
        log.warning("ENTRY aborted: the spot buy did not fill (spot balance unchanged), so no perp short was sent")
        return False
    client.place_market(coin, False, got, SPOT_SLIPPAGE)
    time.sleep(1)
    short, _ = client.position(coin)
    if short >= 0:
        log.error("Perp short did not fill: selling the spot back so the account is not left directional")
        client.place_market(spot_name, False, got, SPOT_SLIPPAGE)
        return False
    log.info("HEDGED: spot +%s %s, perp %s", got, token, short)
    return True


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--coin", default="BTC", help="perp base name with a spot token, e.g. BTC, ETH, HYPE")
    p.add_argument("--min-apr", type=float, default=15.0, help="enter when annualized funding is at least this many percent")
    p.add_argument("--exit-apr", type=float, default=5.0, help="exit when annualized funding falls below this many percent")
    p.add_argument("--order-usd", type=float, default=15.0, help="notional per leg (minimum $10)")
    p.add_argument("--max-loss-usd", type=float, default=15.0, help="stop when equity drops this much")
    p.add_argument("--interval", type=float, default=30.0, help="seconds between loops")
    p.add_argument("--run-seconds", type=float, default=0, help="stop after this many seconds (0 = run until Ctrl+C)")
    p.add_argument("--dry-run", action="store_true", help="log orders instead of sending them")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    setup_logging(args.verbose)
    run(args)


if __name__ == "__main__":
    main()
