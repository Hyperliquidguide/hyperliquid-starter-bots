"""Starter TWAP executor: works a large order in timed slices, maker-first, with a hard price limit.

This is execution tooling, not a strategy. It decides how to fill an order you already chose to
place. Read DISCLAIMER.md.

    python -m bots.twap --coin BTC --side buy --total-usd 200 --minutes 20 --dry-run
    python -m bots.twap --coin ETH --side sell --total-usd 500 --minutes 60 --limit-px 2900
    python -m bots.twap --coin xyz:XYZ100 --side sell --total-usd 300 --minutes 30 --reduce-only

How it works:
1. Split the order into equal slices (each at least Hyperliquid's $10 minimum) spread over
   --minutes.
2. Each slice first rests as a post-only order at the best bid (buy) or best ask (sell), and
   follows the touch if it moves. Fills there pay the maker fee.
3. After --passive-share of the slice's time, cancel what's left of it. With --cross (the
   default), send the remainder as an IOC order capped at --max-slippage-bps from the touch and
   at --limit-px. Without --cross, carry the remainder into the next slice.
4. Stop when the target size is filled, the time is up, or the price is past --limit-px.

Hyperliquid also has a native TWAP order (see the guide linked in the README). Use that when
you only need even slices. This script is for when you want your own rules: maker-first slices,
a price limit you control, a reduce-only unwind, or logic that reacts to the book.
"""

from __future__ import annotations

import argparse
import logging
import math
import time

from hlbots import setup_logging
from hlbots.client import HLClient
from hlbots.config import get_settings
from hlbots.referral import ensure_referral
from hlbots.risk import RiskGuard, RiskLimits
from hlbots.specs import AssetSpec, round_price, round_size

log = logging.getLogger("twap")

MIN_ORDER_USD = 10.0


def plan_slices(total_usd: float, slices: int, min_usd: float = MIN_ORDER_USD) -> list[float]:
    """Equal USD slices, merged into fewer slices if any would fall under the $10 minimum."""
    if total_usd < min_usd:
        raise ValueError(f"total ${total_usd:.2f} is under the ${min_usd:.0f} minimum order value")
    if slices < 1:
        raise ValueError("slices must be at least 1")
    n = min(slices, max(1, math.floor(total_usd / (min_usd * 1.05))))  # 5% headroom for rounding down
    return [total_usd / n] * n


def passive_price(is_buy: bool, bid: float, ask: float) -> float:
    """Join the touch on our side: a post-only buy at the bid, a post-only sell at the ask."""
    return bid if is_buy else ask


def cross_price(is_buy: bool, bid: float, ask: float, max_slippage_bps: float, limit_px: float | None) -> float:
    """Most aggressive price we accept for the IOC catch-up, capped by the user's limit."""
    if is_buy:
        px = ask * (1 + max_slippage_bps / 10_000)
        return min(px, limit_px) if limit_px else px
    px = bid * (1 - max_slippage_bps / 10_000)
    return max(px, limit_px) if limit_px else px


def past_limit(is_buy: bool, bid: float, ask: float, limit_px: float | None) -> bool:
    """True when even our passive price is worse than the limit, so we should pause."""
    if not limit_px:
        return False
    return passive_price(is_buy, bid, ask) > limit_px if is_buy else passive_price(is_buy, bid, ask) < limit_px


def filled_since(start_size: float, now_size: float, is_buy: bool) -> float:
    """Size filled in our direction, from the change in the signed position."""
    delta = now_size - start_size
    return max(0.0, delta if is_buy else -delta)


def slice_size(slice_usd: float, price: float, remaining: float, spec: AssetSpec) -> float:
    """Coin size for one slice, never more than what's left of the order."""
    return round_size(min(slice_usd / price, remaining), spec)


class Twap:
    def __init__(self, client: HLClient, args: argparse.Namespace):
        self.c, self.a = client, args
        self.coin, self.is_buy = args.coin, args.side == "buy"
        self.spec = client.spec(self.coin)

    def _touch(self) -> tuple[float, float]:
        return self.c.book_top(self.coin)

    def _size_now(self) -> float:
        return self.c.position(self.coin)[0]

    def run(self) -> None:
        a, c = self.a, self.c
        slices = plan_slices(a.total_usd, a.slices)
        slice_secs = a.minutes * 60 / len(slices)
        bid, ask = self._touch()
        ref_px = (bid + ask) / 2
        target = round_size(a.total_usd / ref_px, self.spec)
        start_size = self._size_now()
        if a.reduce_only and (start_size == 0 or (start_size > 0) == self.is_buy):
            raise SystemExit("--reduce-only needs an open position on the other side of --side")
        if a.reduce_only:
            target = min(target, round_size(abs(start_size), self.spec))

        guard = RiskGuard(RiskLimits(max_order_usd=a.total_usd, max_position_usd=a.max_position_usd, max_daily_loss_usd=a.max_loss_usd))
        guard.set_start_equity(c.equity())
        log.info(
            "%s %s %s (~$%.0f) in %d slices of ~$%.0f every %.0fs | limit %s | cross %s",
            a.side.upper(), target, self.coin, a.total_usd, len(slices), slices[0], slice_secs,
            a.limit_px or "none", a.cross,
        )

        simulated = 0.0  # dry-run has no fills, so assume each slice fills in full
        for i, slice_usd in enumerate(slices, 1):
            done = simulated if a.dry_run else filled_since(start_size, self._size_now(), self.is_buy)
            remaining = round_size(target - done, self.spec)
            if remaining <= 0:
                break
            if not guard.check_equity(c.equity()):
                break
            slice_end = time.time() + slice_secs
            passive_until = time.time() + slice_secs * a.passive_share
            bid, ask = self._touch()
            if past_limit(self.is_buy, bid, ask, a.limit_px):
                log.info("Slice %d: touch %s/%s is past the limit %s, skipping", i, bid, ask, a.limit_px)
                time.sleep(max(0.0, slice_end - time.time()))
                continue

            # Carry-over: without --cross, unfilled size rolls into later slices.
            left_slices = len(slices) - i + 1
            this_usd = slice_usd if a.cross else max(slice_usd, remaining * ask / left_slices)
            size = slice_size(this_usd, ask if self.is_buy else bid, remaining, self.spec)
            if i == len(slices) or (remaining - size) * bid < MIN_ORDER_USD:
                size = remaining  # last slice, or a leftover too small to send later: take it all now
            pos_usd = abs(self._size_now()) * bid
            if not guard.allow_order(self.is_buy, size * bid, pos_usd if not a.reduce_only else 0.0):
                break

            slice_start = filled_since(start_size, self._size_now(), self.is_buy) if not a.dry_run else simulated
            log.info("Slice %d/%d: %s %s, post-only first", i, len(slices), a.side, size)
            last_px = None
            while time.time() < passive_until:
                bid, ask = self._touch()
                px = round_price(passive_price(self.is_buy, bid, ask), self.spec)
                got = 0.0 if a.dry_run else filled_since(start_size, self._size_now(), self.is_buy) - slice_start
                left = round_size(size - got, self.spec)
                if left <= 0 or left * px < MIN_ORDER_USD:
                    break
                if px != last_px and not past_limit(self.is_buy, bid, ask, a.limit_px):
                    c.cancel_all(self.coin)
                    c.place_limit(self.coin, self.is_buy, left, px, tif="Alo", reduce_only=a.reduce_only)
                    last_px = px
                time.sleep(a.poll)
            c.cancel_all(self.coin)

            got = size if a.dry_run else filled_since(start_size, self._size_now(), self.is_buy) - slice_start
            left = round_size(size - got, self.spec)
            if a.cross and left > 0:
                bid, ask = self._touch()
                px = cross_price(self.is_buy, bid, ask, a.max_slippage_bps, a.limit_px)
                if left * px >= MIN_ORDER_USD:
                    log.info("Slice %d: %s left after the passive phase, crossing with IOC up to %s", i, left, round_price(px, self.spec))
                    c.place_limit(self.coin, self.is_buy, left, px, tif="Ioc", reduce_only=a.reduce_only)
            if a.dry_run:
                simulated += size
            time.sleep(max(0.0, slice_end - time.time()))

        c.cancel_all(self.coin)
        done = simulated if a.dry_run else filled_since(start_size, self._size_now(), self.is_buy)
        log.info("Finished: filled %s of %s %s%s", round_size(done, self.spec), target, self.coin, " (simulated)" if a.dry_run else "")


def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    client = HLClient(settings, [args.coin], dry_run=args.dry_run)
    log.info("Network: %s | market: %s | dry-run: %s", settings.network, args.coin, args.dry_run)
    log.info("Referral: %s", ensure_referral(client.exchange, client.info, client.address, settings.referral_code, settings.referral_enabled, settings.is_mainnet))
    try:
        Twap(client, args).run()
    except KeyboardInterrupt:
        log.info("Stopping (Ctrl+C): cancelling resting orders")
        client.cancel_all(args.coin)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--coin", default="BTC", help="market, e.g. BTC, ETH, xyz:XYZ100")
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--total-usd", type=float, required=True, help="total order value in USD")
    p.add_argument("--minutes", type=float, default=30.0, help="how long to spread the order over")
    p.add_argument("--slices", type=int, default=10, help="number of slices (fewer if a slice would be under $10)")
    p.add_argument("--passive-share", type=float, default=0.7, help="share of each slice spent resting post-only (0-1)")
    p.add_argument("--no-cross", dest="cross", action="store_false", help="never take liquidity; carry unfilled size forward")
    p.add_argument("--max-slippage-bps", type=float, default=10.0, help="IOC catch-up limit from the touch, in basis points")
    p.add_argument("--limit-px", type=float, default=None, help="never buy above / sell below this price")
    p.add_argument("--reduce-only", action="store_true", help="only reduce an existing position")
    p.add_argument("--max-position-usd", type=float, default=1_000.0, help="hard cap on resulting position value")
    p.add_argument("--max-loss-usd", type=float, default=50.0, help="stop when equity drops this much")
    p.add_argument("--poll", type=float, default=3.0, help="seconds between book checks")
    p.add_argument("--dry-run", action="store_true", help="log orders instead of sending them")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    if not 0 <= args.passive_share <= 1:
        p.error("--passive-share must be between 0 and 1")
    setup_logging(args.verbose)
    run(args)


if __name__ == "__main__":
    main()
