"""Print what the bots will see: network, equity, positions, open orders, referral, fee rates.

    python -m scripts.check_account
    python -m scripts.check_account --coin xyz:XYZ100
"""

from __future__ import annotations

import argparse

from hlbots import setup_logging
from hlbots.client import HLClient
from hlbots.config import get_settings
from hlbots.referral import referral_status


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coin", default="BTC")
    args = p.parse_args()
    setup_logging()

    s = get_settings()
    c = HLClient(s, [args.coin], dry_run=True)
    spec = c.spec(args.coin)
    fees = c.info.user_fees(c.address)
    ref = referral_status(c.info, c.address)
    size, entry = c.position(args.coin)

    print(f"network          {s.network}")
    print(f"account          {c.address}")
    print(f"equity           ${c.equity():,.2f}")
    print(f"{args.coin:<16} mid {c.mid(args.coin):.6g} | szDecimals {spec.sz_decimals} | max leverage {spec.max_leverage}x")
    print(f"position         {size} @ {entry}")
    print(f"open orders      {len(c.open_orders(args.coin))}")
    print(f"fee rates        taker {float(fees['userCrossRate']) * 100:.4f}% | maker {float(fees['userAddRate']) * 100:.4f}%")
    print(f"referral         {ref['referred_by'] or 'none'}")


if __name__ == "__main__":
    main()
