"""Price and size rounding. Most "order rejected" errors on Hyperliquid come from here.

Rules (Hyperliquid docs, "Tick and lot size"):
- Size: at most `szDecimals` decimals (per asset, from the `meta` endpoint).
- Price: at most 5 significant figures, and at most (6 - szDecimals) decimals for perps
  or (8 - szDecimals) for spot. Integer prices are always allowed.
- Minimum order value is $10 notional.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MIN_NOTIONAL_USD = 10.0
PERP_MAX_DECIMALS = 6
SPOT_MAX_DECIMALS = 8


@dataclass(frozen=True)
class AssetSpec:
    coin: str  # e.g. "BTC" or "xyz:XYZ100"
    sz_decimals: int
    max_leverage: int
    is_spot: bool = False

    @property
    def max_price_decimals(self) -> int:
        base = SPOT_MAX_DECIMALS if self.is_spot else PERP_MAX_DECIMALS
        return max(base - self.sz_decimals, 0)


def round_size(size: float, spec: AssetSpec) -> float:
    """Round DOWN to the asset's lot size so we never exceed an intended size."""
    factor = 10**spec.sz_decimals
    return math.floor(abs(size) * factor + 1e-9) / factor


def round_price(price: float, spec: AssetSpec) -> float:
    """Round to 5 significant figures and the asset's max price decimals."""
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")
    if price >= 10**5 and float(price).is_integer():
        return float(price)
    sig = float(f"{price:.5g}")
    return round(sig, spec.max_price_decimals)


def size_for_notional(notional_usd: float, price: float, spec: AssetSpec) -> float:
    """Size that spends about `notional_usd`, rounded to lot size. Returns 0 if under $10."""
    if notional_usd < MIN_NOTIONAL_USD:
        return 0.0
    size = round_size(notional_usd / price, spec)
    if size * price < MIN_NOTIONAL_USD:
        # Rounding down pushed it under the minimum; step up one lot.
        size = round_size(size + 10**-spec.sz_decimals, spec)
    return size
