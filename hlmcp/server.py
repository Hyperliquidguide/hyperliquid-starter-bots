"""Hyperliquid Guide MCP server: accurate Hyperliquid facts for coding agents.

Read-only. It holds no keys and places no orders. It gives an agent (Claude Code, Codex, Cursor,
Claude Desktop) what it needs to write correct Hyperliquid code: live market specs, rounding,
funding, error explanations, account and referral status, the agent quickstart, and the source of
the starter bots.

Run:  hl-guide-mcp                      (after `pip install .` in this repo)
      python -m hlmcp.server            (from a clone)

Not affiliated with Hyperliquid or the Hyper Foundation. Nothing it returns is financial advice.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

API = {"mainnet": "https://api.hyperliquid.xyz/info", "testnet": "https://api.hyperliquid-testnet.xyz/info"}
SITE = "https://hyperliquidguide.com"
REPO = "https://github.com/Hyperliquidguide/hyperliquid-starter-bots"
BOTS = ("market_maker", "scalper", "grid", "funding_arb", "twap")
REFERRAL_VOLUME_CUTOFF = 10_000.0

mcp = FastMCP(
    "hyperliquid-guide",
    instructions=(
        "Read-only Hyperliquid reference tools from Hyperliquid Guide (independent, not affiliated with "
        "Hyperliquid). Use market_specs and round_order before writing order code, explain_error when an "
        "order is rejected, and quickstart for endpoints, API wallets, fees and rate limits."
    ),
)


# ---------- helpers ----------

def _post(body: dict[str, Any], network: str = "mainnet") -> Any:
    if network not in API:
        raise ValueError("network must be 'mainnet' or 'testnet'")
    r = requests.post(API[network], json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def _dex(coin: str) -> str:
    return coin.split(":", 1)[0] if ":" in coin else ""


def _round_price(px: float, sz_decimals: int, is_spot: bool = False) -> float:
    if px >= 1e5 and float(px).is_integer():
        return float(px)
    return round(float(f"{px:.5g}"), max((8 if is_spot else 6) - sz_decimals, 0))


def _round_size(sz: float, sz_decimals: int) -> float:
    f = 10**sz_decimals
    return int(abs(sz) * f + 1e-9) / f


def _asset(coin: str, network: str) -> tuple[dict[str, Any], dict[str, Any]]:
    meta, ctxs = _post({"type": "metaAndAssetCtxs", "dex": _dex(coin)}, network)
    for asset, ctx in zip(meta["universe"], ctxs):
        if asset["name"] == coin:
            return asset, ctx
    names = [a["name"] for a in meta["universe"]][:40]
    raise ValueError(f"Unknown market {coin!r} on {network}. HIP-3 markets need a prefix like 'xyz:NVDA'. Some valid names: {names}")


# ---------- tools ----------

@mcp.tool()
def market_specs(coin: str, network: str = "mainnet") -> dict[str, Any]:
    """Live specs for one perp market: size decimals, max price decimals, max leverage, mid/mark price,
    hourly funding and its APR, open interest, and HIP-3 growth mode / fee scale. `coin` is the SDK name:
    'BTC' for native perps, 'xyz:NVDA' for HIP-3 markets."""
    asset, ctx = _asset(coin, network)
    funding = float(ctx.get("funding") or 0)
    mark = float(ctx.get("markPx") or 0)
    return {
        "coin": coin,
        "network": network,
        "szDecimals": asset["szDecimals"],
        "maxPriceDecimals": max(6 - asset["szDecimals"], 0),
        "priceRule": "max 5 significant figures and maxPriceDecimals decimals; integer prices always valid",
        "minOrderUsd": 10,
        "maxLeverage": asset.get("maxLeverage"),
        "onlyIsolated": asset.get("onlyIsolated", False),
        "markPx": mark,
        "midPx": float(ctx["midPx"]) if ctx.get("midPx") else None,
        "fundingHourly": funding,
        "fundingApr": round(funding * 24 * 365 * 100, 2),
        "openInterestUsd": round(float(ctx.get("openInterest") or 0) * mark, 2),
        "dayVolumeUsd": round(float(ctx.get("dayNtlVlm") or 0), 2),
        "growthMode": asset.get("growthMode"),
        "deployerFeeScale": asset.get("deployerFeeScale"),
        "isDelisted": asset.get("isDelisted", False),
    }


@mcp.tool()
def round_order(coin: str, price: float, size: float, network: str = "mainnet") -> dict[str, Any]:
    """Round a price and size to what Hyperliquid accepts for `coin`, and check the $10 minimum.
    Size is rounded down so it never exceeds what you asked for."""
    asset, _ = _asset(coin, network)
    d = asset["szDecimals"]
    px, sz = _round_price(price, d), _round_size(size, d)
    notional = px * sz
    return {
        "price": px,
        "size": sz,
        "notionalUsd": round(notional, 4),
        "valid": sz > 0 and notional >= 10,
        "note": None if notional >= 10 else "Under the $10 minimum: Hyperliquid will reject it. Increase size.",
    }


@mcp.tool()
def top_funding(limit: int = 10, dex: str = "", network: str = "mainnet") -> list[dict[str, Any]]:
    """Markets ranked by absolute funding APR. Positive funding means longs pay shorts every hour.
    `dex` is '' for native perps or a HIP-3 dex name like 'xyz'."""
    meta, ctxs = _post({"type": "metaAndAssetCtxs", "dex": dex}, network)
    rows = []
    for asset, ctx in zip(meta["universe"], ctxs):
        if asset.get("isDelisted"):
            continue
        f = float(ctx.get("funding") or 0)
        mark = float(ctx.get("markPx") or 0)
        rows.append({
            "coin": asset["name"],
            "fundingApr": round(f * 24 * 365 * 100, 2),
            "openInterestUsd": round(float(ctx.get("openInterest") or 0) * mark, 0),
            "dayVolumeUsd": round(float(ctx.get("dayNtlVlm") or 0), 0),
        })
    rows.sort(key=lambda r: abs(r["fundingApr"]), reverse=True)
    return rows[: max(1, min(limit, 50))]


ERRORS = [
    (r"invalid price", "Price has too many decimals or significant figures.", "Round to max 5 significant figures and (6 - szDecimals) decimals for perps, (8 - szDecimals) for spot. Use round_order."),
    (r"invalid size", "Size has more decimals than szDecimals.", "Round size down to szDecimals. Use round_order."),
    (r"minimum value of \$10", "Order notional is under $10.", "Increase size. Check again after rounding down."),
    (r"post only order would have immediately matched", "An Alo (post-only) price crossed the book.", "Quote at or behind the best bid (buys) or best ask (sells)."),
    (r"could not immediately match", "An IOC order found no liquidity at its limit price.", "Widen slippage, or use a resting order."),
    (r"insufficient margin", "Not enough collateral at the current leverage.", "Reduce size, add collateral, or raise leverage with update_leverage."),
    (r"does not exist", "The signing wallet isn't an approved API wallet for this account, or the account was never funded.", "Approve the API wallet from the main wallet, pass account_address=MAIN_ADDRESS, and deposit first."),
    (r"referrer already set", "The account already has a referrer.", "Nothing to do. It can't be changed."),
    (r"too many cumulative requests|rate limit", "Address or IP rate limit hit.", "Batch orders, poll less often, use the WebSocket. Address limits grow with traded volume."),
    (r"nonce", "Nonce reused, stale or out of order.", "Use one API wallet per process and a fresh millisecond timestamp per action."),
    (r"unknown|coin", "Market name not recognized.", "Names are case-sensitive. HIP-3 needs a prefix like 'xyz:NVDA', and the SDK needs perp_dexs including that dex."),
]


@mcp.tool()
def explain_error(message: str) -> dict[str, str]:
    """Explain a Hyperliquid order or API error and how to fix it. Paste the exact error text.
    Remember: a rejected order still returns HTTP 200; the error is in response.data.statuses[i]."""
    low = message.lower()
    for pattern, cause, fix in ERRORS:
        if re.search(pattern, low):
            return {"cause": cause, "fix": fix}
    return {
        "cause": "Not in our table.",
        "fix": f"Check the full error table at {SITE}/agents/quickstart.md and the API guide at {SITE}/guides/trading/hyperliquid-api-guide.md",
    }


@mcp.tool()
def account_status(address: str, network: str = "mainnet") -> dict[str, Any]:
    """Read-only snapshot of a main account: equity (perp + spot USDC), open positions, fee rates, and
    referral status including whether a referral code can still be added. Never pass a private key."""
    perp = _post({"type": "clearinghouseState", "user": address}, network)
    spot = _post({"type": "spotClearinghouseState", "user": address}, network)
    fees = _post({"type": "userFees", "user": address}, network)
    ref = _post({"type": "referral", "user": address}, network)
    usdc = sum(float(b["total"]) for b in spot.get("balances", []) if b["coin"] == "USDC")
    volume = float(ref.get("cumVlm") or 0)
    referred = ref.get("referredBy")
    if referred:
        eligible = "no: " + ("already has referrer " + str(referred.get("code")) if referred.get("code") not in (None, "", "N/A") else "past the referral window")
    elif volume >= REFERRAL_VOLUME_CUTOFF:
        eligible = "no: over ~$10K lifetime volume"
    else:
        eligible = "yes: no referrer and under ~$10K volume (measured on testnet, Nov 2026)"
    return {
        "equityUsd": round(float(perp["marginSummary"]["accountValue"]) + usdc, 2),
        "positions": [
            {"coin": p["position"]["coin"], "size": p["position"]["szi"], "entryPx": p["position"].get("entryPx"),
             "unrealizedPnl": p["position"].get("unrealizedPnl"), "liquidationPx": p["position"].get("liquidationPx")}
            for p in perp.get("assetPositions", [])
        ],
        "takerFee": fees.get("userCrossRate"),
        "makerFee": fees.get("userAddRate"),
        "lifetimeVolumeUsd": volume,
        "referredBy": (referred or {}).get("code"),
        "canAddReferralCode": eligible,
    }


@mcp.tool()
def quickstart() -> str:
    """The Hyperliquid bot quickstart for coding agents: endpoints, API wallets, market names, rounding,
    exact error messages, fees, rate limits, referral behavior and safety defaults."""
    return resources.files("hlmcp").joinpath("quickstart.md").read_text(encoding="utf-8")


@mcp.tool()
def starter_bot(kind: str) -> str:
    """Source code of one starter bot (market_maker, scalper, grid, funding_arb, twap) from the open-source
    hyperliquid-starter-bots repo, with how to run it. The bots depend on the repo's hlbots package,
    so clone the repo rather than copying a single file."""
    if kind not in BOTS:
        return f"Unknown bot {kind!r}. Choose one of: {', '.join(BOTS)}"
    try:
        src = resources.files("bots").joinpath(f"{kind}.py").read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError):
        src = (Path(__file__).resolve().parent.parent / "bots" / f"{kind}.py").read_text(encoding="utf-8")
    header = (
        f"# Run it:\n#   git clone {REPO}\n#   cd hyperliquid-starter-bots && pip install -r requirements.txt\n"
        f"#   python -m scripts.setup_wallet   # testnet API wallet\n#   python -m bots.{kind} --dry-run\n"
        "# No returns are promised. Testnet first.\n\n"
    )
    return header + src


@mcp.resource("hyperliquid-guide://quickstart")
def quickstart_resource() -> str:
    """The agent quickstart as a resource."""
    return quickstart()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
