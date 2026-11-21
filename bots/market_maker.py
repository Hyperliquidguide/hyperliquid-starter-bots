"""Starter market maker: quotes a post-only bid and ask around the mid, leaning against inventory.

This is a starting point to build on, not a strategy with an edge. Read DISCLAIMER.md.

    python -m bots.market_maker --coin BTC --dry-run
    python -m bots.market_maker --coin xyz:XYZ100 --spread-bps 8 --order-usd 25

How it works, each loop:
1. Read mid price, position and equity. Stop if the daily loss limit is hit.
2. Compute bid/ask: half the spread each side, shifted against inventory (long -> quotes move
   down so the ask fills first; short -> quotes move up).
3. If quotes moved more than --requote-bps since last time, cancel and re-post them as Alo
   (post-only), so they never cross the book and always pay maker fees.

Ideas to build on: quote off the order-book microprice instead of the mid, widen the spread when
volatility rises, quote several levels, use bulk_modify instead of cancel/replace, react to fills
over the websocket instead of polling, hedge inventory on another venue.
"""

from __future__ import annotations

import argparse
import logging
import time

from hlbots import setup_logging
from hlbots.client import HLClient
from hlbots.config import get_settings
from hlbots.referral import ensure_referral
from hlbots.risk import RiskGuard, RiskLimits
from hlbots.specs import size_for_notional

log = logging.getLogger("market_maker")


def compute_quotes(mid: float, spread_bps: float, position_usd: float, max_position_usd: float, skew_bps: float) -> tuple[float, float]:
    """Bid and ask around `mid`. Inventory skew shifts both quotes by up to `skew_bps`."""
    half = spread_bps / 2 / 10_000
    inventory = max(-1.0, min(1.0, position_usd / max_position_usd)) if max_position_usd > 0 else 0.0
    shift = -inventory * skew_bps / 10_000
    center = mid * (1 + shift)
    return center * (1 - half), center * (1 + half)


def moved_bps(old: float | None, new: float) -> float:
    return float("inf") if not old else abs(new - old) / old * 10_000


def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    client = HLClient(settings, [args.coin], dry_run=args.dry_run)
    log.info("Network: %s | market: %s | dry-run: %s", settings.network, args.coin, args.dry_run)
    log.info("Referral: %s", ensure_referral(client.exchange, client.info, client.address, settings.referral_code, settings.referral_enabled, settings.is_mainnet))

    guard = RiskGuard(RiskLimits(args.order_usd, args.max_position_usd, args.max_loss_usd))
    spec = client.spec(args.coin)
    last_bid = last_ask = None

    try:
        while True:
            if not guard.check_equity(client.equity()):
                break
            mid = client.mid(args.coin)
            size, _ = client.position(args.coin)
            position_usd = size * mid
            bid, ask = compute_quotes(mid, args.spread_bps, position_usd, args.max_position_usd, args.skew_bps)

            if moved_bps(last_bid, bid) >= args.requote_bps or moved_bps(last_ask, ask) >= args.requote_bps:
                client.cancel_all(args.coin)
                for is_buy, px in ((True, bid), (False, ask)):
                    qty = size_for_notional(args.order_usd, px, spec)
                    if qty and guard.allow_order(is_buy, qty * px, position_usd):
                        client.place_limit(args.coin, is_buy, qty, px, tif="Alo")
                last_bid, last_ask = bid, ask
                log.info("mid %.6g | pos $%.2f | quotes %.6g / %.6g", mid, position_usd, bid, ask)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Stopping (Ctrl+C)")
    finally:
        client.cancel_all(args.coin)
        if guard.halted and args.flatten_on_halt:
            client.close_position(args.coin)
        log.info("Open orders cancelled. Position left as is%s.", " (flattened)" if guard.halted and args.flatten_on_halt else "")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--coin", default="BTC", help="market, e.g. BTC, ETH, xyz:XYZ100")
    p.add_argument("--spread-bps", type=float, default=10.0, help="total quoted spread in basis points")
    p.add_argument("--skew-bps", type=float, default=5.0, help="max quote shift at full inventory")
    p.add_argument("--requote-bps", type=float, default=2.0, help="re-post quotes after this much movement")
    p.add_argument("--order-usd", type=float, default=15.0, help="notional per quote (minimum $10)")
    p.add_argument("--max-position-usd", type=float, default=100.0)
    p.add_argument("--max-loss-usd", type=float, default=20.0, help="stop when equity drops this much")
    p.add_argument("--interval", type=float, default=3.0, help="seconds between loops")
    p.add_argument("--flatten-on-halt", action="store_true", help="market-close the position if the loss limit hits")
    p.add_argument("--dry-run", action="store_true", help="log orders instead of sending them")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    setup_logging(args.verbose)
    run(args)


if __name__ == "__main__":
    main()
