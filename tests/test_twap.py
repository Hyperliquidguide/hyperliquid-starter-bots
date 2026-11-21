"""Offline tests for the TWAP helpers. No network, no keys."""

import pytest

from bots.twap import cross_price, filled_since, passive_price, past_limit, plan_slices, slice_size
from hlbots.specs import AssetSpec

BTC = AssetSpec("BTC", 5, 40)


def test_plan_slices_even():
    assert plan_slices(200, 10) == pytest.approx([20.0] * 10)


def test_plan_slices_merges_when_slices_would_be_under_minimum():
    s = plan_slices(50, 10)  # $5 slices are not allowed, so fewer, bigger ones
    assert len(s) == 4 and all(x >= 10 for x in s) and sum(s) == pytest.approx(50)


def test_plan_slices_rejects_tiny_orders():
    with pytest.raises(ValueError):
        plan_slices(9, 3)
    with pytest.raises(ValueError):
        plan_slices(100, 0)


def test_passive_price_joins_our_side():
    assert passive_price(True, 99.0, 101.0) == 99.0
    assert passive_price(False, 99.0, 101.0) == 101.0


def test_cross_price_respects_slippage_and_limit():
    assert cross_price(True, 99.0, 100.0, 10, None) == pytest.approx(100.1)
    assert cross_price(False, 100.0, 101.0, 10, None) == pytest.approx(99.9)
    assert cross_price(True, 99.0, 100.0, 50, 100.2) == pytest.approx(100.2)  # capped at the limit
    assert cross_price(False, 100.0, 101.0, 50, 99.8) == pytest.approx(99.8)


def test_past_limit():
    assert past_limit(True, 101.0, 102.0, 100.0)  # bid already above our max buy price
    assert not past_limit(True, 99.0, 100.0, 100.0)
    assert past_limit(False, 98.0, 99.0, 100.0)  # ask already below our min sell price
    assert not past_limit(False, 100.0, 101.0, None)


def test_filled_since_counts_only_our_direction():
    assert filled_since(0.0, 0.3, True) == pytest.approx(0.3)
    assert filled_since(0.5, 0.2, False) == pytest.approx(0.3)  # selling reduces a long
    assert filled_since(0.0, -0.1, True) == 0.0  # moved the wrong way: nothing filled for us


def test_slice_size_never_exceeds_remaining():
    assert slice_size(20, 50_000, 1.0, BTC) == pytest.approx(0.0004)
    assert slice_size(20, 50_000, 0.0002, BTC) == pytest.approx(0.0002)
