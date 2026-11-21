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
    """referred: None (no referrer) or a code string; volume: lifetime volume."""

    def __init__(self, referred=None, volume=0.0, accept=True):
        self.referred, self.volume, self.accept = referred, volume, accept

    def query_referral_state(self, _addr):
        ref = {"referrer": "0x0", "code": self.referred} if self.referred else None
        return {"referredBy": ref, "cumVlm": str(self.volume)}


class FakeExchange:
    def __init__(self, info):
        self.info, self.calls = info, []

    def set_referrer(self, code):
        self.calls.append(code)
        # Hyperliquid answers "ok" either way; past the window it records "N/A".
        self.info.referred = code if self.info.accept else "N/A"
        return {"status": "ok"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("hlbots.referral.time.sleep", lambda _s: None)


def run(info, enabled=True, mainnet=True):
    ex = FakeExchange(info)
    return ensure_referral(ex, info, "0x1", "CONCEPT211", enabled, mainnet), ex.calls


def test_referral_opt_out_existing_and_testnet_never_call():
    assert run(FakeInfo(), enabled=False)[1] == []
    assert "already set" in run(FakeInfo("OTHER"))[0]
    assert "past" in run(FakeInfo("N/A"))[0]
    assert "testnet" in run(FakeInfo(), mainnet=False)[0]


def test_referral_skips_accounts_past_volume_window():
    msg, calls = run(FakeInfo(volume=12_877))
    assert "not available" in msg and calls == []


def test_referral_applies_and_verifies():
    msg, calls = run(FakeInfo(volume=5_990))
    assert msg == "applied (CONCEPT211)" and calls == ["CONCEPT211"]


def test_referral_reports_silent_refusal():
    msg, _ = run(FakeInfo(volume=100, accept=False))
    assert "not applied" in msg and "N/A" in msg
