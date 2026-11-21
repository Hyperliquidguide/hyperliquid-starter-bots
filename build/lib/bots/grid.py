"""Starter grid bot: post-only buys below the price and sells above it, re-armed one level over on each fill.

This is a starting point to build on, not a strategy with an edge. Read DISCLAIMER.md.

    python -m bots.grid --coin BTC --dry-run
    python -m bots.grid --coin ETH --lower 3000 --upper 3300 --levels 8 --order-usd 15

What it does: it lays a ladder of resting limit orders at evenly spaced prices between a lower and
an upper bound. Every time one fills it places the opposite order one rung away, so the bot keeps
buying lower rungs and selling higher rungs while price moves inside the range.

How it works, step by step:
1. Build the price ladder with grid_levels(): --levels evenly spaced prices from --lower to --upper.
   If you leave --lower/--upper out, they default to the mid price -/+ --range-pct percent.
2. Cancel any leftover orders on the market, then place post-only (Alo) buys on every rung below
   the mid and post-only sells on every rung above it. Post-only means an order is rejected rather
   than crossing the book, so the grid always pays maker fees.
3. Each loop, check equity against the daily loss limit, then list the open orders.
4. A rung whose order id vanished from the open orders either filled or was cancelled. The bot
   confirms with client.info.user_fills. A filled buy at rung i becomes a sell at rung i+1; a filled
   sell at rung i becomes a buy at rung i-1 (replacement_for_fill). An order that disappeared
   without a fill is simply placed again after a short grace period (fills can lag the order list).
5. Every new order goes through RiskGuard.allow_order, so once the position hits --max-position-usd
   the grid stops adding to it (buys when long, sells when short) and only reducing orders go out.
6. On exit (including --run-seconds) all open orders are cancelled. The position is left as is.

Ideas to build on: geometric (percentage) spacing instead of arithmetic, shift the whole grid when
price leaves the range, size rungs by distance from the center, skip rungs near the mid so fees do
not eat a rung, react to fills over the websocket instead of polling, add a stop that closes the
position if price breaks out of the range.
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
from hlbots.specs import size_for_notional

log = logging.getLogger("grid")

# Loops an order may be missing from open orders, with no matching fill, before it is placed again.
MISSING_GRACE_LOOPS = 2


def grid_levels(lower: float, upper: float, levels: int) -> list[float]:
    """`levels` evenly spaced prices from `lower` to `upper`, both included, ascending."""
    if levels < 2:
        raise ValueError("a grid needs at least 2 levels")
    if lower <= 0 or upper <= lower:
        raise ValueError(f"need 0 < lower < upper, got lower={lower} upper={upper}")
    step = (upper - lower) / (levels - 1)
    return [lower + i * step for i in range(levels)]


def default_range(mid: float, range_pct: float) -> tuple[float, float]:
    """Lower and upper bound used when the user passes none: mid -/+ range_pct percent."""
    return mid * (1 - range_pct / 100), mid * (1 + range_pct / 100)


def initial_orders(prices: list[float], mid: float) -> list[tuple[int, bool]]:
    """(rung index, is_buy) for the first ladder: buys below the mid, sells above it.
    A rung sitting exactly on the mid is skipped, because neither side would be post-only safe."""
    out = []
    for i, px in enumerate(prices):
        if px < mid:
            out.append((i, True))
        elif px > mid:
            out.append((i, False))
    return out


def replacement_for_fill(idx: int, is_buy: bool, n_levels: int) -> tuple[int, bool] | None:
    """The order to place after the order at rung `idx` fills.
    A filled buy re-arms as a sell one rung up; a filled sell re-arms as a buy one rung down.
    Returns None at the edge of the grid (nothing above the top or below the bottom)."""
    new_idx = idx + 1 if is_buy else idx - 1
    if 0 <= new_idx < n_levels:
        return new_idx, not is_buy
    return None


def extract_oid(res: Any) -> int | None:
    """Order id from an exchange response if the order is resting (or filled), else None."""
    try:
        status = res["response"]["data"]["statuses"][0]
    except (TypeError, KeyError, IndexError):
        return None
    for key in ("resting", "filled"):
        if key in status:
            return int(status[key]["oid"])
    return None


def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    client = HLClient(settings, [args.coin], dry_run=args.dry_run)
    log.info("Network: %s | market: %s | dry-run: %s", settings.network, args.coin, args.dry_run)
    log.info("Referral: %s", ensure_referral(client.exchange, client.info, client.address, settings.referral_code, settings.referral_enabled, settings.is_mainnet))

    guard = RiskGuard(RiskLimits(args.order_usd * 1.25, args.max_position_usd, args.max_loss_usd))
    spec = client.spec(args.coin)

    mid = client.mid(args.coin)
    lower, upper = args.lower, args.upper
    if lower is None and upper is None:
        lower, upper = default_range(mid, args.range_pct)
    elif lower is None or upper is None:
        raise SystemExit("Pass both --lower and --upper, or neither (then --range-pct is used).")
    prices = grid_levels(lower, upper, args.levels)
    log.info("Grid: %d levels from %.6g to %.6g (step %.6g) | mid %.6g", len(prices), lower, upper, prices[1] - prices[0], mid)

    tracked: dict[int, tuple[int, bool]] = {}  # rung -> (order id, is_buy)
    missing: dict[int, int] = {}  # rung -> consecutive loops its order was not in open orders

    def place(idx: int, is_buy: bool, position_usd: float) -> None:
        if idx in tracked:
            return
        px = prices[idx]
        qty = size_for_notional(args.order_usd, px, spec)
        if not qty or not guard.allow_order(is_buy, qty * px, position_usd):
            return
        oid = extract_oid(client.place_limit(args.coin, is_buy, qty, px, tif="Alo"))
        if oid is not None:
            tracked[idx] = (oid, is_buy)

    deadline = time.time() + args.run_seconds if args.run_seconds else None
    try:
        if not guard.check_equity(client.equity()):
            return
        client.cancel_all(args.coin)  # start from a clean book
        size, _ = client.position(args.coin)
        for idx, is_buy in initial_orders(prices, mid):
            place(idx, is_buy, size * mid)
        log.info("Placed %d grid orders (%d resting)", len(initial_orders(prices, mid)), len(tracked))

        while deadline is None or time.time() < deadline:
            time.sleep(args.interval)
            if not guard.check_equity(client.equity()):
                break
            mid = client.mid(args.coin)
            size, _ = client.position(args.coin)
            position_usd = size * mid

            open_oids = {int(o["oid"]) for o in client.open_orders(args.coin)}
            gone = [i for i, (oid, _) in tracked.items() if oid not in open_oids]
            if gone:
                filled_oids = {int(f["oid"]) for f in client.info.user_fills(client.address) if f["coin"] == args.coin}
                for idx in gone:
                    oid, is_buy = tracked[idx]
                    if oid in filled_oids:
                        del tracked[idx]
                        missing.pop(idx, None)
                        log.info("FILLED %s at rung %d (%.6g) | pos $%.2f", "buy" if is_buy else "sell", idx, prices[idx], position_usd)
                        nxt = replacement_for_fill(idx, is_buy, len(prices))
                        if nxt:
                            place(nxt[0], nxt[1], position_usd)
                    else:
                        missing[idx] = missing.get(idx, 0) + 1
                        if missing[idx] >= MISSING_GRACE_LOOPS:
                            log.warning("Order at rung %d vanished without a fill; placing it again", idx)
                            del tracked[idx]
                            missing.pop(idx)
                            place(idx, is_buy, position_usd)
            log.info("mid %.6g | pos $%.2f | %d orders resting", mid, position_usd, len(open_oids))
    except KeyboardInterrupt:
        log.info("Stopping (Ctrl+C)")
    finally:
        client.cancel_all(args.coin)
        log.info("Open orders cancelled. Position left as is.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--coin", default="BTC", help="market, e.g. BTC, ETH, xyz:XYZ100")
    p.add_argument("--lower", type=float, default=None, help="lowest grid price (default: mid - range-pct)")
    p.add_argument("--upper", type=float, default=None, help="highest grid price (default: mid + range-pct)")
    p.add_argument("--range-pct", type=float, default=1.0, help="half-width of the default range, in percent of the mid")
    p.add_argument("--levels", type=int, default=6, help="number of grid prices, lower and upper included")
    p.add_argument("--order-usd", type=float, default=12.0, help="notional per grid order (minimum $10)")
    p.add_argument("--max-position-usd", type=float, default=60.0, help="stop adding to a position beyond this")
    p.add_argument("--max-loss-usd", type=float, default=15.0, help="stop when equity drops this much")
    p.add_argument("--interval", type=float, default=3.0, help="seconds between loops")
    p.add_argument("--run-seconds", type=float, default=0, help="stop after this many seconds (0 = run until Ctrl+C)")
    p.add_argument("--dry-run", action="store_true", help="log orders instead of sending them")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    setup_logging(args.verbose)
    run(args)


if __name__ == "__main__":
    main()
