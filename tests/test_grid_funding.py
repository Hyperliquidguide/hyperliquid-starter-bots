"""Offline tests for the grid and funding_arb helpers. No network, no keys."""

import pytest

from bots.funding_arb import find_spot_pair, funding_rate, hedge_size, hourly_to_apr, should_enter, should_exit
from bots.grid import default_range, extract_oid, grid_levels, initial_orders, replacement_for_fill
from hlbots.client import is_spot_name
from hlbots.specs import AssetSpec, round_price

# ---------- grid ----------


def test_grid_levels_even_and_inclusive():
    assert grid_levels(100, 200, 5) == pytest.approx([100, 125, 150, 175, 200])


@pytest.mark.parametrize("lower,upper,levels", [(100, 100, 5), (200, 100, 5), (100, 200, 1), (0, 10, 3)])
def test_grid_levels_rejects_bad_input(lower, upper, levels):
    with pytest.raises(ValueError):
        grid_levels(lower, upper, levels)


def test_default_range():
    lo, hi = default_range(100.0, 2.0)
    assert lo == pytest.approx(98) and hi == pytest.approx(102)


def test_initial_orders_split_around_mid():
    prices = [90, 95, 100, 105, 110]
    assert initial_orders(prices, 102) == [(0, True), (1, True), (2, True), (3, False), (4, False)]
    # a rung exactly on the mid is skipped
    assert (2, True) not in initial_orders(prices, 100) and (2, False) not in initial_orders(prices, 100)


def test_replacement_for_fill():
    assert replacement_for_fill(2, True, 6) == (3, False)  # buy filled -> sell one up
    assert replacement_for_fill(2, False, 6) == (1, True)  # sell filled -> buy one down
    assert replacement_for_fill(5, True, 6) is None  # nothing above the top rung
    assert replacement_for_fill(0, False, 6) is None  # nothing below the bottom rung


def test_extract_oid():
    resting = {"response": {"data": {"statuses": [{"resting": {"oid": 123}}]}}}
    filled = {"response": {"data": {"statuses": [{"filled": {"oid": 7, "totalSz": "1", "avgPx": "1"}}]}}}
    rejected = {"response": {"data": {"statuses": [{"error": "Post only order would have immediately matched"}]}}}
    assert extract_oid(resting) == 123 and extract_oid(filled) == 7
    assert extract_oid(rejected) is None and extract_oid(None) is None


# ---------- funding_arb ----------


def test_hourly_to_apr():
    assert hourly_to_apr(0.0000125) == pytest.approx(0.1095)  # the default 0.01%/8h rate is 10.95% APR
    assert hourly_to_apr(-0.00001) < 0


def test_enter_exit_decisions():
    assert should_enter(0.20, 0.15, hedged=False)
    assert not should_enter(0.10, 0.15, hedged=False)
    assert not should_enter(0.50, 0.15, hedged=True)  # already in
    assert should_exit(0.02, 0.05, hedged=True)
    assert not should_exit(0.08, 0.05, hedged=True)  # between exit and entry thresholds: hold
    assert not should_exit(0.01, 0.05, hedged=False)  # nothing to close


SPOT_META = {
    "tokens": [
        {"name": "USDC", "index": 0, "szDecimals": 8},
        {"name": "PURR", "index": 1, "szDecimals": 0},
        {"name": "UBTC", "index": 2, "szDecimals": 5},
        {"name": "UBTC", "index": 3, "szDecimals": 5},  # non-canonical duplicate
        {"name": "HYPE", "index": 4, "szDecimals": 2},
    ],
    "universe": [
        {"name": "PURR/USDC", "tokens": [1, 0], "index": 0, "isCanonical": True},
        {"name": "@7", "tokens": [3, 0], "index": 7, "isCanonical": False},
        {"name": "@5", "tokens": [2, 0], "index": 5, "isCanonical": True},
        {"name": "@9", "tokens": [4, 0], "index": 9, "isCanonical": True},
        {"name": "@11", "tokens": [4, 2], "index": 11, "isCanonical": True},  # HYPE/UBTC, not USDC
    ],
}


def test_find_spot_pair_prefix_canonical_and_plain():
    assert find_spot_pair(SPOT_META, "BTC") == ("@5", "UBTC")  # U prefix, canonical wins
    assert find_spot_pair(SPOT_META, "HYPE") == ("@9", "HYPE")  # plain name, USDC quote only
    assert find_spot_pair(SPOT_META, "PURR") == ("PURR/USDC", "PURR")
    assert find_spot_pair(SPOT_META, "DOGE") is None


def test_hedge_size_uses_coarser_lot():
    spot = AssetSpec("@5", 5, 1, is_spot=True)
    perp = AssetSpec("BTC", 3, 40)
    size = hedge_size(15, 90_000, spot, perp)
    assert size == round(size, 3) and size * 90_000 >= 10


def test_funding_rate_lookup():
    data = [{"universe": [{"name": "BTC"}, {"name": "ETH"}]}, [{"funding": "0.0000125"}, {"funding": "-0.00002"}]]
    assert funding_rate(data, "ETH") == pytest.approx(-0.00002)
    assert funding_rate(data, "SOL") is None


# ---------- client helpers ----------


def test_spot_names_and_spot_price_decimals():
    assert is_spot_name("@107") and is_spot_name("PURR/USDC")
    assert not is_spot_name("BTC") and not is_spot_name("xyz:XYZ100")
    spot = AssetSpec("@5", 5, 1, is_spot=True)
    perp = AssetSpec("BTC", 5, 40)
    assert spot.max_price_decimals == 3 and perp.max_price_decimals == 1
    assert round_price(1.234567, spot) == 1.235
