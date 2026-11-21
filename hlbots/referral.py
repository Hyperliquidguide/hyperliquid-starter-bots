"""Referral code setup, with the disclosure printed every time it runs.

What it does: if your account has no referrer yet, it applies the Hyperliquid Guide referral
code. Hyperliquid gives your account 4% off trading fees on your first $25M of volume, and pays
Hyperliquid Guide a share of the fees you pay. You pay less, not more.

Opt out with HL_REFERRAL=off. It never changes an existing referrer.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

DISCLOSURE = (
    "Referral: this starter kit applies the Hyperliquid Guide referral code ({code}) to accounts "
    "that have none. Hyperliquid gives you 4% off fees on your first $25M of volume and pays "
    "Hyperliquid Guide a share of your fees. Set HL_REFERRAL=off to skip."
)


def referral_status(info: Any, address: str) -> dict[str, Any]:
    state = info.query_referral_state(address)
    return {
        "referred_by": (state.get("referredBy") or {}).get("code"),
        "volume": float(state.get("cumVlm") or 0),
    }


def ensure_referral(exchange: Any, info: Any, address: str, code: str, enabled: bool, is_mainnet: bool) -> str:
    """Returns a short status string. Never raises: a referral problem must not stop a bot."""
    if not enabled:
        return "skipped (HL_REFERRAL=off)"
    try:
        status = referral_status(info, address)
    except Exception as exc:  # network hiccup: carry on without it
        return f"skipped (could not read referral state: {exc})"
    if status["referred_by"]:
        return f"already set ({status['referred_by']})"
    if not is_mainnet and code == "CONCEPT211":
        return "skipped on testnet (the code only exists on mainnet)"

    log.info(DISCLOSURE.format(code=code))
    try:
        res = exchange.set_referrer(code)
    except Exception as exc:
        return f"not applied ({exc})"
    if isinstance(res, dict) and res.get("status") == "ok":
        return f"applied ({code})"
    return f"not applied ({res})"
