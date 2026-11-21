"""Opt-in order tools for the Hyperliquid Guide MCP server.

OFF unless the MCP client's config sets HL_MCP_TRADING=on. When on:
- It signs with an API (agent) wallet only. A main-wallet key is refused, because an API wallet can
  trade but cannot withdraw. There are no withdraw or transfer tools at all.
- Testnet unless HL_NETWORK=mainnet AND HL_MCP_ALLOW_MAINNET=yes.
- Every order is two calls: prepare_order returns a preview (rounded price and size, notional, fee
  estimate) and a one-time token; place_order(token) sends it. Tokens expire after 2 minutes. Show
  the preview to the person and get a clear yes before placing.
- Hard caps in code: HL_MCP_MAX_ORDER_USD (default 25) per order, HL_MCP_MAX_POSITION_USD (default 100).

Environment: HL_ACCOUNT_ADDRESS (main account), HL_SECRET_KEY (API wallet key), HL_NETWORK.
Referral: on the first order it applies the Hyperliquid Guide code to an account that has none
(4% off fees on the first $25M of volume; Hyperliquid pays Hyperliquid Guide a share of fees),
says so in the response, and skips it with HL_REFERRAL=off.
"""

from __future__ import annotations

import functools
import os
import secrets
import time
from typing import Any

TOKEN_TTL = 120
_pending: dict[str, dict[str, Any]] = {}
_referral_done = False


def _safe(fn):
    """The bot library exits on config errors (SystemExit); turn that into a normal tool error."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SystemExit as e:
            raise ValueError(str(e)) from None
    return wrapper


def enabled() -> bool:
    return os.environ.get("HL_MCP_TRADING", "").lower() == "on"


def _limits() -> tuple[float, float]:
    return float(os.environ.get("HL_MCP_MAX_ORDER_USD", "25")), float(os.environ.get("HL_MCP_MAX_POSITION_USD", "100"))


def _client(coin: str):
    import eth_account

    from hlbots.client import HLClient
    from hlbots.config import get_settings

    s = get_settings(require_keys=True)
    if s.is_mainnet and os.environ.get("HL_MCP_ALLOW_MAINNET", "").lower() != "yes":
        raise PermissionError("Mainnet orders are off. Set HL_MCP_ALLOW_MAINNET=yes in the MCP config to allow them.")
    if eth_account.Account.from_key(s.secret_key).address.lower() == s.account_address.lower():
        raise PermissionError(
            "HL_SECRET_KEY is the main wallet key. Order tools only run with an API wallet key, which can trade "
            "but cannot withdraw. Create one with `python -m scripts.setup_wallet` or at app.hyperliquid.xyz/API."
        )
    return s, HLClient(s, [coin])


def _status(res: Any) -> str:
    try:
        st = res["response"]["data"]["statuses"][0]
    except (TypeError, KeyError, IndexError):
        return f"unexpected response: {res}"
    if "error" in st:
        return f"REJECTED: {st['error']}"
    kind = next(iter(st))
    detail = st[kind]
    if kind == "filled":
        return f"filled {detail.get('totalSz')} @ {detail.get('avgPx')} (oid {detail.get('oid')})"
    if kind == "resting":
        return f"resting (oid {detail.get('oid')})"
    return kind


def register(mcp) -> None:
    """Add the order tools to the FastMCP server. Call only when enabled()."""

    @mcp.tool()
    @_safe
    def trading_status() -> dict[str, Any]:
        """Order tools status: network, account, caps, and current position and open orders per market are
        available through account_status. Call this first to confirm which network orders will go to."""
        from hlbots.config import get_settings

        s = get_settings(require_keys=True)
        max_order, max_pos = _limits()
        return {
            "network": s.network,
            "account": s.account_address,
            "mainnetAllowed": os.environ.get("HL_MCP_ALLOW_MAINNET", "").lower() == "yes",
            "maxOrderUsd": max_order,
            "maxPositionUsd": max_pos,
            "flow": "prepare_order -> show the preview to the person -> place_order(token) only after a clear yes",
            "noWithdrawals": "There are no withdraw or transfer tools, and the API wallet cannot withdraw.",
        }

    @mcp.tool()
    @_safe
    def prepare_order(coin: str, side: str, usd: float, limit_price: float | None = None,
                      post_only: bool = True, reduce_only: bool = False) -> dict[str, Any]:
        """Build an order preview and a one-time confirm token. Nothing is sent. `side` is 'buy' or 'sell',
        `usd` the notional. With post_only (default) and no limit_price it joins the best bid (buy) or ask
        (sell) as a maker order; post_only=False sends an IOC at limit_price, or within 1% of the mid if none.
        Show the returned preview to the person and get explicit approval before calling place_order."""
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        from hlbots.specs import round_price, round_size

        s, c = _client(coin)
        spec = c.spec(coin)
        is_buy = side == "buy"
        bid, ask = c.book_top(coin)
        mid = (bid + ask) / 2
        if limit_price:
            px = limit_price
        elif post_only:
            px = bid if is_buy else ask
        else:
            px = mid * (1.01 if is_buy else 0.99)
        px = round_price(px, spec)
        size = round_size(usd / px, spec)
        notional = size * px
        max_order, max_pos = _limits()
        pos, _ = c.position(coin)
        pos_usd = pos * mid
        after = pos_usd + (notional if is_buy else -notional)
        problems = []
        if notional < 10:
            problems.append(f"notional ${notional:.2f} is under Hyperliquid's $10 minimum")
        if notional > max_order:
            problems.append(f"notional ${notional:.2f} is over HL_MCP_MAX_ORDER_USD ${max_order:.0f}")
        if abs(after) > max_pos and abs(after) > abs(pos_usd) and not reduce_only:
            problems.append(f"position would be ${after:.2f}, over HL_MCP_MAX_POSITION_USD ${max_pos:.0f}")
        if reduce_only and (pos == 0 or (pos > 0) == is_buy):
            problems.append("reduce_only needs an open position on the other side")
        tif = "Alo" if post_only else "Ioc"
        fees = c.info.user_fees(s.account_address)
        rate = float(fees.get("userAddRate" if post_only else "userCrossRate") or 0)
        preview = {
            "network": s.network, "coin": coin, "side": side, "size": size, "price": px, "tif": tif,
            "reduceOnly": reduce_only, "notionalUsd": round(notional, 2), "book": {"bid": bid, "ask": ask},
            "positionBeforeUsd": round(pos_usd, 2), "positionAfterUsd": round(after, 2),
            "estimatedFeeUsd": round(notional * rate, 4),
        }
        if problems:
            return {"ok": False, "preview": preview, "problems": problems}
        token = secrets.token_hex(4)
        _pending[token] = {**preview, "expires": time.time() + TOKEN_TTL}
        return {"ok": True, "preview": preview, "confirmToken": token, "expiresInSeconds": TOKEN_TTL,
                "next": "Show this preview to the person. Call place_order with the token only after they approve it."}

    @mcp.tool()
    @_safe
    def place_order(confirm_token: str) -> dict[str, Any]:
        """Send an order previously built by prepare_order. Only call this after the person approved that
        exact preview. Tokens are single-use and expire after 2 minutes."""
        global _referral_done
        order = _pending.pop(confirm_token, None)
        if not order:
            return {"ok": False, "error": "Unknown or already used token. Call prepare_order again."}
        if time.time() > order["expires"]:
            return {"ok": False, "error": "Token expired. Call prepare_order again so the price is fresh."}
        s, c = _client(order["coin"])
        out: dict[str, Any] = {}
        if not _referral_done:
            from hlbots.referral import DISCLOSURE, ensure_referral

            status = ensure_referral(c.exchange, c.info, c.address, s.referral_code, s.referral_enabled, s.is_mainnet)
            out["referral"] = status
            if status.startswith("applied"):
                out["referralDisclosure"] = DISCLOSURE.format(code=s.referral_code)
            _referral_done = True
        res = c.place_limit(order["coin"], order["side"] == "buy", order["size"], order["price"],
                            tif=order["tif"], reduce_only=order["reduceOnly"])
        out.update({"ok": True, "order": {k: order[k] for k in ("network", "coin", "side", "size", "price", "tif")},
                    "result": _status(res)})
        return out

    @mcp.tool()
    @_safe
    def cancel_orders(coin: str) -> dict[str, Any]:
        """Cancel every open order on one market for the configured account."""
        _, c = _client(coin)
        n = len(c.open_orders(coin))
        c.cancel_all(coin)
        return {"ok": True, "cancelled": n, "remaining": len(c.open_orders(coin))}
