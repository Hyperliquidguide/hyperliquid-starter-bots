"""Settings, read from environment variables (or a local .env file).

Everything that touches money is opt-in: the default network is testnet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from hyperliquid.utils import constants

REPO_ROOT = Path(__file__).resolve().parent.parent

# Referral code for Hyperliquid Guide (hyperliquidguide.com). See README "Referral disclosure".
# It only exists on mainnet. Set HL_REFERRAL=off to skip it, or HL_REFERRAL_CODE to use another.
DEFAULT_REFERRAL_CODE = "CONCEPT211"


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env loader so the repo needs no extra dependency. Real env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    network: str  # "testnet" or "mainnet"
    account_address: str  # your main wallet address (the account that holds funds)
    secret_key: str  # API (agent) wallet key that signs orders. Never your main wallet key.
    referral_enabled: bool
    referral_code: str

    @property
    def is_mainnet(self) -> bool:
        return self.network == "mainnet"

    @property
    def api_url(self) -> str:
        return constants.MAINNET_API_URL if self.is_mainnet else constants.TESTNET_API_URL


def get_settings(require_keys: bool = True) -> Settings:
    load_dotenv()
    network = os.environ.get("HL_NETWORK", "testnet").strip().lower()
    if network not in ("testnet", "mainnet"):
        raise SystemExit(f"HL_NETWORK must be 'testnet' or 'mainnet', got {network!r}")

    account = os.environ.get("HL_ACCOUNT_ADDRESS", "").strip()
    secret = os.environ.get("HL_SECRET_KEY", "").strip()
    if require_keys and (not account or not secret):
        raise SystemExit(
            "Missing HL_ACCOUNT_ADDRESS or HL_SECRET_KEY. Run `python -m scripts.setup_wallet` "
            "first, or copy .env.example to .env and fill it in."
        )

    referral = os.environ.get("HL_REFERRAL", "on").strip().lower() not in ("off", "0", "false", "no")
    code = os.environ.get("HL_REFERRAL_CODE", DEFAULT_REFERRAL_CODE).strip()
    return Settings(network, account, secret, referral, code)
