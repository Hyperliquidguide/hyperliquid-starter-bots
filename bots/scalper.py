"""Starter momentum scalper: EMA crossover entries with native take-profit and stop-loss orders.

This is a starting point to build on, not a strategy with an edge. Read DISCLAIMER.md.

    python -m bots.scalper --coin ETH --dry-run
    python -m bots.scalper --coin SOL --interval 5m --order-usd 20

How it works:
1. Pull recent candles, compute a fast and a slow EMA and the average true range (ATR).
2. Fast crosses above slow -> buy. Fast crosses below slow -> sell short. Only when flat.
3. Right after the fill, place reduce-only trigger orders on Hyperliquid itself:
   stop-loss at entry -/+ ATR x --stop-atr, take-profit at entry +/- ATR x --tp-atr.
   They live on the exchange, so they still fire if this script dies.
4. Wait for the position to close, cancel the leftover trigger, repeat.

Ideas to build on: add a trend or volatility filter, trade only certain hours, use funding rate
as a bias, trail the stop, size by ATR so each trade risks the same dollars.
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

log = logging.getLogger("scalper")


def ema(values: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def atr(candles: list[dict], period: int = 14) -> float:
    trs = []
    for prev, cur in zip(candles, candles[1:]):
        h, l, pc = float(cur["h"]), float(cur["l"]), float(prev["c"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def signal(closes: list[float], fast: int, slow: int) -> int:
    """+1 on a fresh bullish cross, -1 on a fresh bearish cross, 0 otherwise. Uses closed candles only."""
    if len(closes) < slow + 2:
        return 0
    f, s = ema(closes, fast), ema(closes, slow)
    before, now = f[-2] - s[-2], f[-1] - s[-1]
    if before <= 0 < now:
        return 1
    if before >= 0 > now:
        return -1
    return 0


def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    client = HLClient(settings, [args.coin], dry_run=args.dry_run)
    log.info("Network: %s | market: %s | dry-run: %s", settings.network, args.coin, args.dry_run)
    log.info("Referral: %s", ensure_referral(client.exchange, client.info, client.address, settings.referral_code, settings.referral_enabled, settings.is_mainnet))

    guard = RiskGuard(RiskLimits(args.order_usd, args.order_usd, args.max_loss_usd))
    spec = client.spec(args.coin)
    last_candle_t = None

    try:
        while True:
            if not guard.check_equity(client.equity()):
                client.cancel_all(args.coin)
                client.close_position(args.coin)
                break

            candles = client.candles(args.coin, args.interval, lookback=args.slow * 4)
            closed = candles[:-1]  # the last candle is still forming
            if not closed or closed[-1]["t"] == last_candle_t:
                time.sleep(args.poll)
                continue
            last_candle_t = closed[-1]["t"]

            size, _ = client.position(args.coin)
            if size != 0:
                time.sleep(args.poll)
                continue
            client.cancel_all(args.coin)  # leftover TP/SL from the last trade

            sig = signal([float(c["c"]) for c in closed], args.fast, args.slow)
            if sig == 0:
                continue
            is_buy = sig > 0
            mid = client.mid(args.coin)
            qty = size_for_notional(args.order_usd, mid, spec)
            if not qty or not guard.allow_order(is_buy, qty * mid, 0.0):
                continue

            vol = atr(closed)
            log.info("%s signal | mid %.6g | ATR %.6g", "LONG" if is_buy else "SHORT", mid, vol)
            client.place_market(args.coin, is_buy, qty)
            filled, entry = client.position(args.coin)
            if filled == 0 and not args.dry_run:
                log.warning("Entry did not fill; waiting for the next signal")
                continue
            entry = entry or mid
            sign = 1 if is_buy else -1
            client.place_trigger(args.coin, not is_buy, abs(filled) or qty, entry - sign * vol * args.stop_atr, "sl")
            client.place_trigger(args.coin, not is_buy, abs(filled) or qty, entry + sign * vol * args.tp_atr, "tp")
    except KeyboardInterrupt:
        log.info("Stopping (Ctrl+C). Exchange-side TP/SL orders stay active for any open position.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--coin", default="ETH", help="market, e.g. BTC, ETH, SOL, xyz:XYZ100")
    p.add_argument("--interval", default="1m", choices=["1m", "5m", "15m", "1h"])
    p.add_argument("--fast", type=int, default=9)
    p.add_argument("--slow", type=int, default=21)
    p.add_argument("--stop-atr", type=float, default=1.5, help="stop distance in ATRs")
    p.add_argument("--tp-atr", type=float, default=2.0, help="take-profit distance in ATRs")
    p.add_argument("--order-usd", type=float, default=15.0, help="notional per trade (minimum $10)")
    p.add_argument("--max-loss-usd", type=float, default=20.0, help="stop when equity drops this much")
    p.add_argument("--poll", type=float, default=10.0, help="seconds between checks")
    p.add_argument("--dry-run", action="store_true", help="log orders instead of sending them")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    setup_logging(args.verbose)
    run(args)


if __name__ == "__main__":
    main()
