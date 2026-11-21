"""One-time setup: create an API wallet for your bots and write .env.

    python -m scripts.setup_wallet            # testnet (default)
    python -m scripts.setup_wallet --mainnet

What it does:
1. Asks for your MAIN wallet's private key (hidden input, never saved to disk).
2. Approves a fresh API wallet ("agent") on your account. API wallets can place and cancel orders
   but cannot withdraw funds. Your bots use that key, not your main key.
3. Applies the referral code if your account has none (disclosed below; HL_REFERRAL=off skips it).
4. Writes HL_NETWORK, HL_ACCOUNT_ADDRESS and HL_SECRET_KEY to .env (which is gitignored).

Prefer to do it by hand? Create an API wallet at app.hyperliquid.xyz -> More -> API, then fill
in .env from .env.example.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

from hlbots.config import DEFAULT_REFERRAL_CODE, REPO_ROOT, load_dotenv
from hlbots.referral import DISCLOSURE, ensure_referral


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mainnet", action="store_true", help="set up a mainnet account (default: testnet)")
    p.add_argument("--agent-name", default="starter-bots", help="label shown in the Hyperliquid API page")
    args = p.parse_args()
    load_dotenv()

    network = "mainnet" if args.mainnet else "testnet"
    url = constants.MAINNET_API_URL if args.mainnet else constants.TESTNET_API_URL
    referral_on = os.environ.get("HL_REFERRAL", "on").lower() not in ("off", "0", "false", "no")
    code = os.environ.get("HL_REFERRAL_CODE", DEFAULT_REFERRAL_CODE)

    print(f"\nSetting up a {network.upper()} API wallet.\n")
    if referral_on:
        print(DISCLOSURE.format(code=code) + "\n")

    key = os.environ.get("HL_MASTER_KEY") or getpass.getpass("Main wallet private key (input hidden): ")
    key = key.strip()
    try:
        master = eth_account.Account.from_key(key)
    except Exception:
        sys.exit("That is not a valid private key.")
    print(f"Main wallet: {master.address}")

    info = Info(url, skip_ws=True)
    exchange = Exchange(master, url)

    # Referral first: it is signed by the main wallet, before any trading.
    print("Referral:", ensure_referral(exchange, info, master.address, code, referral_on, args.mainnet))

    res, agent_key = exchange.approve_agent(args.agent_name)
    if not isinstance(res, dict) or res.get("status") != "ok":
        sys.exit(f"Approving the API wallet failed: {res}\nDoes the account have a deposit on {network}?")
    agent = eth_account.Account.from_key(agent_key)
    print(f"API wallet approved: {agent.address} (name: {args.agent_name})")

    env_path = REPO_ROOT / ".env"
    lines = [ln for ln in (env_path.read_text().splitlines() if env_path.exists() else [])
             if not ln.startswith(("HL_NETWORK=", "HL_ACCOUNT_ADDRESS=", "HL_SECRET_KEY="))]
    lines += [f"HL_NETWORK={network}", f"HL_ACCOUNT_ADDRESS={master.address}", f"HL_SECRET_KEY={agent_key}"]
    env_path.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {env_path}. Your main key was not saved.")
    print("Next: python -m scripts.check_account, then try a bot with --dry-run.")


if __name__ == "__main__":
    main()
