"""Offline tests: no network, no keys. Run with `python -m pytest`."""


import pytest

from bots.market_maker import compute_quotes, moved_bps
from bots.scalper import atr, ema, signal
from hlbots.referral import ensure_referral
from hlbots.risk import RiskGuard, RiskLimits
from hlbots.specs import AssetSpec, round_price, round_size, size_for_notional

BTC = AssetSpec("BTC", sz_decimals=5, max_leverage=40)
DOGE = AssetSpec("DOGE", sz_decimals=0, max_leverage=10)


# ---------- specs ----------

def test_round_size_floors_to_lot():
    assert round_size(0.123456789, BTC) == 0.12345
    assert round_size(17.9, DOGE) == 17


def test_round_price_sig_figs_and_decimals():
    assert round_price(97123.456, BTC) == 97123.0  # 5 sig figs
    assert round_price(0.1234567, DOGE) == 0.12346  # 5 sig figs, 6 decimals allowed
    assert round_price(123456.0, BTC) == 123456.0  # integer prices always allowed


def test_size_for_notional_respects_minimum():
    assert size_for_notional(5, 100_000, BTC) == 0.0
    size = size_for_notional(10, 97_000, BTC)
    assert size * 97_000 >= 10


# ---------- risk ----------

def test_risk_blocks_oversized_and_position_growth():
    g = RiskGuard(RiskLimits(max_order_usd=50, max_position_usd=100, max_daily_loss_usd=10))
    assert not g.allow_order(True, 60, 0)  # order too big
    assert g.allow_order(True, 50, 60) is False  # would reach $110 long
    assert g.allow_order(False, 50, 120)  # reducing is always fine


def test_risk_halts_on_loss():
    g = RiskGuard(RiskLimits(max_daily_loss_usd=10))
    assert g.check_equity(1000)
    assert g.check_equity(995)
    assert not g.check_equity(989)
    assert not g.allow_order(True, 1, 0)


# ---------- market maker ----------

def test_quotes_symmetric_when_flat():
    bid, ask = compute_quotes(100.0, spread_bps=10, position_usd=0, max_position_usd=100, skew_bps=5)
    assert bid == pytest.approx(99.95) and ask == pytest.approx(100.05)


def test_quotes_lean_against_inventory():
    flat_bid, flat_ask = compute_quotes(100.0, 10, 0, 100, 5)
    long_bid, long_ask = compute_quotes(100.0, 10, 100, 100, 5)
    assert long_bid < flat_bid and long_ask < flat_ask  # long -> sell more eagerly


def test_moved_bps():
    assert moved_bps(None, 1) == float("inf")
    assert moved_bps(100, 100.02) == pytest.approx(2)


# ---------- scalper ----------

def test_ema_and_cross_signal():
    up = [10.0] * 30 + [10.5, 11, 11.5, 12]
    assert ema([1, 1, 1], 3) == [1, 1, 1]
    # a cross only fires on the candle where it happens
    sigs = [signal(up[:i], 3, 8) for i in range(10, len(up) + 1)]
    assert sigs.count(1) == 1 and -1 not in sigs


def test_atr():
    candles = [{"h": 11, "l": 9, "c": 10}] * 20
    assert atr(candles) == pytest.approx(2)


# ---------- referral ----------

class FakeInfo:
    def __init__(self, referred_by=None):
        self.referred_by = referred_by

    def query_referral_state(self, _addr):
        return {"referredBy": {"code": self.referred_by} if self.referred_by else None, "cumVlm": "0"}


class FakeExchange:
    def __init__(self):
        self.calls = []

    def set_referrer(self, code):
        self.calls.append(code)
        return {"status": "ok"}


def test_referral_respects_opt_out_and_existing():
    ex = FakeExchange()
    assert "skipped" in ensure_referral(ex, FakeInfo(), "0x1", "CONCEPT211", enabled=False, is_mainnet=True)
    assert "already set" in ensure_referral(ex, FakeInfo("OTHER"), "0x1", "CONCEPT211", True, True)
    assert "testnet" in ensure_referral(ex, FakeInfo(), "0x1", "CONCEPT211", True, False)
    assert ex.calls == []
    assert "applied" in ensure_referral(ex, FakeInfo(), "0x1", "CONCEPT211", True, True)
    assert ex.calls == ["CONCEPT211"]
