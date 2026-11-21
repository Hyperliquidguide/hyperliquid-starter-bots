"""Thin wrapper around the official hyperliquid-python-sdk.

One object gives a bot what it needs: market specs, mid price, position, equity, and order
helpers that round prices and sizes correctly. HIP-3 markets use a dex prefix, e.g. "xyz:XYZ100".
"""

from __future__ import annotations

import logging
import time
from typing import Any

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from .config import Settings
from .specs import AssetSpec, round_price, round_size

log = logging.getLogger(__name__)


def dex_of(coin: str) -> str:
    """'xyz:XYZ100' -> 'xyz'; 'BTC' -> '' (the native perp dex)."""
    return coin.split(":", 1)[0] if ":" in coin else ""


class HLClient:
    def __init__(self, settings: Settings, coins: list[str], dry_run: bool = False):
        self.settings = settings
        self.dry_run = dry_run
        self.address = settings.account_address
        dexs = sorted({dex_of(c) for c in coins} | {""})
        self.info = Info(settings.api_url, skip_ws=True, perp_dexs=dexs)
        wallet = eth_account.Account.from_key(settings.secret_key)
        self.exchange = Exchange(wallet, settings.api_url, account_address=self.address, perp_dexs=dexs)
        self._specs: dict[str, AssetSpec] = {}
        if wallet.address.lower() == self.address.lower():
            log.warning(
                "HL_SECRET_KEY is your main wallet key. Prefer an API wallet: it can trade but cannot withdraw."
            )

    # ---------- market data ----------

    def spec(self, coin: str) -> AssetSpec:
        if coin not in self._specs:
            meta = self.info.meta(dex=dex_of(coin))
            for asset in meta["universe"]:
                if asset["name"] == coin:
                    self._specs[coin] = AssetSpec(coin, asset["szDecimals"], asset.get("maxLeverage", 1))
                    break
            else:
                raise SystemExit(f"Unknown market {coin!r}. HIP-3 markets need their prefix, e.g. 'xyz:XYZ100'.")
        return self._specs[coin]

    def mid(self, coin: str) -> float:
        return float(self.info.all_mids(dex_of(coin))[coin])

    def book_top(self, coin: str) -> tuple[float, float]:
        """Best bid and best ask."""
        levels = self.info.l2_snapshot(coin)["levels"]
        return float(levels[0][0]["px"]), float(levels[1][0]["px"])

    def candles(self, coin: str, interval: str = "1m", lookback: int = 100) -> list[dict[str, Any]]:
        minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}[interval]
        end = int(time.time() * 1000)
        start = end - lookback * minutes * 60_000
        return self.info.candles_snapshot(coin, interval, start, end)

    # ---------- account ----------

    def position(self, coin: str) -> tuple[float, float]:
        """(signed size, entry price) for one market. Zero if flat."""
        state = self.info.user_state(self.address, dex_of(coin))
        for p in state["assetPositions"]:
            pos = p["position"]
            if pos["coin"] == coin:
                return float(pos["szi"]), float(pos.get("entryPx") or 0)
        return 0.0, 0.0

    def equity(self) -> float:
        """Perp account value plus spot USDC. Unified accounts hold collateral in spot, so count both."""
        perp = float(self.info.user_state(self.address)["marginSummary"]["accountValue"])
        spot = 0.0
        for bal in self.info.spot_user_state(self.address).get("balances", []):
            if bal["coin"] == "USDC":
                spot = float(bal["total"])
        return perp + spot

    def open_orders(self, coin: str) -> list[dict[str, Any]]:
        return [o for o in self.info.open_orders(self.address, dex_of(coin)) if o["coin"] == coin]

    # ---------- orders ----------

    def place_limit(self, coin: str, is_buy: bool, size: float, price: float, tif: str = "Alo", reduce_only: bool = False) -> Any:
        """Alo = post-only (maker), Gtc = rests on the book, Ioc = take liquidity now."""
        spec = self.spec(coin)
        size, price = round_size(size, spec), round_price(price, spec)
        if size <= 0:
            return None
        tag = f"{'BUY' if is_buy else 'SELL'} {size} {coin} @ {price} ({tif}{', reduce-only' if reduce_only else ''})"
        if self.dry_run:
            log.info("[dry-run] %s", tag)
            return None
        res = self.exchange.order(coin, is_buy, size, price, {"limit": {"tif": tif}}, reduce_only=reduce_only)
        return self._check(res, tag)

    def place_market(self, coin: str, is_buy: bool, size: float, slippage: float = 0.01) -> Any:
        """Aggressive IOC limit order, which is how Hyperliquid does market orders."""
        spec = self.spec(coin)
        size = round_size(size, spec)
        px = self.mid(coin) * (1 + slippage if is_buy else 1 - slippage)
        return self.place_limit(coin, is_buy, size, px, tif="Ioc")

    def place_trigger(self, coin: str, is_buy: bool, size: float, trigger_px: float, kind: str) -> Any:
        """Native take-profit (kind='tp') or stop-loss (kind='sl'), reduce-only, executes as market."""
        spec = self.spec(coin)
        size, trigger_px = round_size(size, spec), round_price(trigger_px, spec)
        tag = f"{kind.upper()} {'BUY' if is_buy else 'SELL'} {size} {coin} trigger {trigger_px}"
        if self.dry_run:
            log.info("[dry-run] %s", tag)
            return None
        order_type = {"trigger": {"triggerPx": trigger_px, "isMarket": True, "tpsl": kind}}
        res = self.exchange.order(coin, is_buy, size, trigger_px, order_type, reduce_only=True)
        return self._check(res, tag)

    def cancel_all(self, coin: str) -> None:
        orders = self.open_orders(coin)
        if not orders:
            return
        if self.dry_run:
            log.info("[dry-run] cancel %d open %s orders", len(orders), coin)
            return
        self.exchange.bulk_cancel([{"coin": coin, "oid": o["oid"]} for o in orders])

    def close_position(self, coin: str) -> None:
        size, _ = self.position(coin)
        if size == 0:
            return
        if self.dry_run:
            log.info("[dry-run] close %s position %s", coin, size)
            return
        self._check(self.exchange.market_close(coin), f"close {coin}")

    @staticmethod
    def _check(res: Any, tag: str) -> Any:
        """Log the outcome. Hyperliquid returns HTTP 200 even when an order is rejected."""
        try:
            statuses = res["response"]["data"]["statuses"]
        except (TypeError, KeyError):
            log.error("%s -> unexpected response: %s", tag, res)
            return res
        for st in statuses:
            if "error" in st:
                log.error("%s -> REJECTED: %s", tag, st["error"])
            else:
                log.info("%s -> %s", tag, next(iter(st)))
        return res
