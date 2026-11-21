"""Referral code setup, with the disclosure printed every time it runs.

What it does: if your account has no referrer yet, it applies the Hyperliquid Guide referral
code. Hyperliquid gives your account 4% off trading fees on your first $25M of volume, and pays
Hyperliquid Guide a share of the fees you pay. You pay less, not more.

Opt out with HL_REFERRAL=off. It never changes an existing referrer.

How Hyperliquid handles it (measured on testnet, 2026-11-21):
- An API (agent) wallet can set the referrer for the account it trades for.
- It still works after the account has traded: applied at $5,990 of volume, refused at $12,877.
  The cutoff looks like $10,000, the same volume needed to create a code.
- Past the cutoff the API still answers "ok" but records referrer "N/A", so check the state
  afterwards instead of trusting the response.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# Above this lifetime volume Hyperliquid no longer accepts a referrer (see module docstring).
REFERRAL_VOLUME_CUTOFF = 10_000.0
NO_REFERRER_CODES = {None, "", "N/A"}

DISCLOSURE = (
    "Referral: this starter kit applies the Hyperliquid Guide referral code ({code}) to accounts "
    "that have none. Hyperliquid gives you 4% off fees on your first $25M of volume and pays "
    "Hyperliquid Guide a share of your fees. Set HL_REFERRAL=off to skip."
)


def referral_status(info: Any, address: str) -> dict[str, Any]:
    state = info.query_referral_state(address)
    referred = state.get("referredBy")
    return {
        "referred_by": (referred or {}).get("code"),
        "locked": referred is not None,  # any referredBy entry, even "N/A", means it can't change
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
    if status["locked"]:
        if status["referred_by"] in NO_REFERRER_CODES:
            return "not available (this account is past Hyperliquid's referral window)"
        return f"already set ({status['referred_by']})"
    if status["volume"] >= REFERRAL_VOLUME_CUTOFF:
        return f"not available (account volume ${status['volume']:,.0f} is past the ~$10K referral window)"
    if not is_mainnet and code == "CONCEPT211":
        return "skipped on testnet (the code only exists on mainnet)"

    log.info(DISCLOSURE.format(code=code))
    try:
        res = exchange.set_referrer(code)
    except Exception as exc:
        return f"not applied ({exc})"
    if not (isinstance(res, dict) and res.get("status") == "ok"):
        return f"not applied ({res})"
    # "ok" is not proof: re-read the state.
    for _ in range(3):
        time.sleep(1)
        try:
            after = referral_status(info, address)
        except Exception:
            continue
        if after["referred_by"] == code.upper() or after["referred_by"] == code:
            return f"applied ({code})"
        if after["locked"]:
            return f"not applied (Hyperliquid recorded {after['referred_by']!r})"
    return f"sent ({code}); confirm with `python -m scripts.check_account`"
