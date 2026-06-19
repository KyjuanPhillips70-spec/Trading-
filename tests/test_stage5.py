"""Tests for Stage 5 — news.py, risk.py, contracts.py.

Network calls (Tradier, ForexFactory) are monkeypatched; the math and
selection logic are verified against hand-built fixtures.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

import contracts
import news
import risk
from contracts import Contract, choose_expiration, select_contract, settlement_note
from risk import compute_risk, estimate_option_pl


# ============================================================
# risk.py
# ============================================================

def _contract(delta: float = 0.5, gamma: float = 0.01, mid: float = 2.0) -> Contract:
    return Contract(
        symbol="TEST", option_type="call", strike=100.0, expiry=date(2024, 1, 19),
        dte=10, bid=1.9, ask=2.1, mid=mid, delta=delta, theta=-0.05, gamma=gamma,
        vega=0.1, iv=0.3, oi=100, volume=50, settlement_note="x",
    )


class TestComputeRisk:
    def test_long_uses_one_to_one_fallback(self):
        # entry 100, stop anchor 98 (-0.1*ATR buffer), no pool → 1:1 target.
        rs = compute_risk(
            entry=100.0, sweep_extreme=98.0, ob_far_edge=98.5,
            next_liquidity_pool=None, direction="long", atr_value=1.0,
            stop_buffer_atr=0.1, min_rr=1.0,
        )
        assert rs is not None
        # stop = min(98, 98.5) - 0.1 = 97.9; risk = 2.1; target = 100 + 2.1 = 102.1
        assert rs.stop == pytest.approx(97.9)
        assert rs.risk == pytest.approx(2.1)
        assert rs.target == pytest.approx(102.1)
        assert rs.rr == pytest.approx(1.0)

    def test_short_uses_one_to_one_fallback(self):
        rs = compute_risk(
            entry=100.0, sweep_extreme=102.0, ob_far_edge=101.5,
            next_liquidity_pool=None, direction="short", atr_value=1.0,
            stop_buffer_atr=0.1, min_rr=1.0,
        )
        assert rs is not None
        # stop = max(102, 101.5) + 0.1 = 102.1; risk = 2.1; target = 100 - 2.1 = 97.9
        assert rs.stop == pytest.approx(102.1)
        assert rs.target == pytest.approx(97.9)
        assert rs.rr == pytest.approx(1.0)

    def test_liquidity_pool_target_when_rr_sufficient(self):
        rs = compute_risk(
            entry=100.0, sweep_extreme=98.0, ob_far_edge=98.0,
            next_liquidity_pool=110.0, direction="long", atr_value=1.0,
            stop_buffer_atr=0.1, min_rr=1.0,
        )
        assert rs is not None
        # risk = 2.1; pool reward = 10 → rr ≈ 4.76 ≥ 1 → use pool.
        assert rs.target == pytest.approx(110.0)
        assert rs.rr > 1.0

    def test_pool_too_close_falls_back_to_one_to_one(self):
        rs = compute_risk(
            entry=100.0, sweep_extreme=98.0, ob_far_edge=98.0,
            next_liquidity_pool=100.5, direction="long", atr_value=1.0,
            stop_buffer_atr=0.1, min_rr=1.0,
        )
        assert rs is not None
        # pool reward 0.5 < risk 2.1 → fall back to exactly 1:1.
        assert rs.target == pytest.approx(102.1)

    def test_pool_in_wrong_direction_ignored(self):
        rs = compute_risk(
            entry=100.0, sweep_extreme=98.0, ob_far_edge=98.0,
            next_liquidity_pool=90.0, direction="long", atr_value=1.0,
        )
        assert rs is not None
        assert rs.target == pytest.approx(102.1)  # 1:1 fallback

    def test_zero_risk_returns_none(self):
        rs = compute_risk(
            entry=100.0, sweep_extreme=100.0, ob_far_edge=100.0,
            next_liquidity_pool=None, direction="long", atr_value=0.0,
            stop_buffer_atr=0.0,
        )
        assert rs is None

    def test_option_pl_populated_with_contract(self):
        c = _contract(delta=0.5, gamma=0.0, mid=2.0)
        rs = compute_risk(
            entry=100.0, sweep_extreme=98.0, ob_far_edge=98.0,
            next_liquidity_pool=None, direction="long", atr_value=1.0,
            contract=c,
        )
        assert rs is not None
        assert rs.option_debit == pytest.approx(2.0)
        # gain on +2.1 move with delta 0.5 → 0.5*2.1*100 = 105
        assert rs.option_gain == pytest.approx(105.0)
        # loss on -2.1 move → -105, but floored at -mid*100 = -200 → -105 stands
        assert rs.option_loss == pytest.approx(-105.0)


class TestEstimateOptionPL:
    def test_linear_delta(self):
        c = _contract(delta=0.5, gamma=0.0, mid=2.0)
        assert estimate_option_pl(c, 4.0) == pytest.approx(0.5 * 4.0 * 100)

    def test_gamma_second_order(self):
        c = _contract(delta=0.5, gamma=0.1, mid=2.0)
        # 0.5*4 + 0.5*0.1*16 = 2 + 0.8 = 2.8 → *100 = 280
        assert estimate_option_pl(c, 4.0) == pytest.approx(280.0)

    def test_loss_floored_at_premium(self):
        c = _contract(delta=0.5, gamma=0.0, mid=2.0)
        # a -10 move → -500, but max loss is -mid*100 = -200
        assert estimate_option_pl(c, -10.0) == pytest.approx(-200.0)


# ============================================================
# contracts.py
# ============================================================

class TestSettlementNote:
    def test_spx_cash_settled(self):
        assert "Cash-settled" in settlement_note("SPX")
        assert "Section 1256" in settlement_note("SPX")

    def test_equity_default(self):
        assert "American-style" in settlement_note("NVDA")
        assert "American-style" in settlement_note("UNKNOWN")


class TestChooseExpiration:
    def test_prefers_in_range(self):
        today = date(2024, 1, 1)
        exps = ["2024-01-05", "2024-01-10", "2024-01-20"]  # dte 4, 9, 19
        res = choose_expiration(exps, today, dte_min=7, dte_max=14)
        assert res == ("2024-01-10", 9)

    def test_fallback_smallest_above_min(self):
        today = date(2024, 1, 1)
        exps = ["2024-01-05", "2024-01-25", "2024-02-10"]  # dte 4, 24, 40
        res = choose_expiration(exps, today, dte_min=7, dte_max=14)
        assert res == ("2024-01-25", 24)

    def test_none_when_all_below_min(self):
        today = date(2024, 1, 1)
        exps = ["2024-01-03", "2024-01-05"]  # dte 2, 4
        assert choose_expiration(exps, today, dte_min=7, dte_max=14) is None


def _fake_chain() -> pd.DataFrame:
    return pd.DataFrame([
        # calls
        {"symbol": "C20", "option_type": "call", "strike": 95, "bid": 6.0, "ask": 6.2,
         "open_interest": 500, "volume": 100, "delta": 0.80, "gamma": 0.01,
         "theta": -0.05, "vega": 0.1, "mid_iv": 0.30},
        {"symbol": "C50", "option_type": "call", "strike": 100, "bid": 3.0, "ask": 3.2,
         "open_interest": 1000, "volume": 300, "delta": 0.55, "gamma": 0.02,
         "theta": -0.06, "vega": 0.12, "mid_iv": 0.31},
        {"symbol": "C25", "option_type": "call", "strike": 105, "bid": 1.0, "ask": 1.1,
         "open_interest": 200, "volume": 50, "delta": 0.25, "gamma": 0.03,
         "theta": -0.04, "vega": 0.08, "mid_iv": 0.33},
        # puts
        {"symbol": "P55", "option_type": "put", "strike": 100, "bid": 2.8, "ask": 3.0,
         "open_interest": 800, "volume": 250, "delta": -0.50, "gamma": 0.02,
         "theta": -0.06, "vega": 0.12, "mid_iv": 0.32},
    ])


class TestSelectContract:
    def test_long_selects_call_in_delta_band(self, monkeypatch):
        monkeypatch.setattr(contracts.tradier, "get_option_expirations",
                            lambda t: ["2024-01-10"])
        monkeypatch.setattr(contracts.tradier, "get_option_chain",
                            lambda t, e: _fake_chain())
        c = select_contract("NVDA", "long", 100, 98, 104, today=date(2024, 1, 1))
        assert c is not None
        assert c.option_type == "call"
        assert c.symbol == "C50"          # delta 0.55 in [0.45,0.65]
        assert 0.45 <= abs(c.delta) <= 0.65
        assert c.mid == pytest.approx(3.1)
        assert c.oi == 1000
        assert "American-style" in c.settlement_note

    def test_short_selects_put(self, monkeypatch):
        monkeypatch.setattr(contracts.tradier, "get_option_expirations",
                            lambda t: ["2024-01-10"])
        monkeypatch.setattr(contracts.tradier, "get_option_chain",
                            lambda t, e: _fake_chain())
        c = select_contract("NVDA", "short", 100, 102, 96, today=date(2024, 1, 1))
        assert c is not None
        assert c.option_type == "put"
        assert c.symbol == "P55"

    def test_rejects_low_delta_only_chain(self, monkeypatch):
        chain = pd.DataFrame([
            {"symbol": "LOW", "option_type": "call", "strike": 120, "bid": 0.1,
             "ask": 0.2, "open_interest": 10, "volume": 1, "delta": 0.10,
             "gamma": 0.01, "theta": -0.01, "vega": 0.01, "mid_iv": 0.30},
        ])
        monkeypatch.setattr(contracts.tradier, "get_option_expirations",
                            lambda t: ["2024-01-10"])
        monkeypatch.setattr(contracts.tradier, "get_option_chain",
                            lambda t, e: chain)
        c = select_contract("NVDA", "long", 100, 98, 104, today=date(2024, 1, 1))
        assert c is None

    def test_no_expirations_returns_none(self, monkeypatch):
        monkeypatch.setattr(contracts.tradier, "get_option_expirations", lambda t: [])
        c = select_contract("NVDA", "long", 100, 98, 104, today=date(2024, 1, 1))
        assert c is None

    def test_iv_warning_flagged(self, monkeypatch):
        chain = pd.DataFrame([
            {"symbol": "A", "option_type": "call", "strike": 100, "bid": 3.0,
             "ask": 3.2, "open_interest": 100, "volume": 50, "delta": 0.55,
             "gamma": 0.02, "theta": -0.06, "vega": 0.12, "mid_iv": 0.90},
            {"symbol": "B", "option_type": "call", "strike": 101, "bid": 2.0,
             "ask": 2.2, "open_interest": 100, "volume": 50, "delta": 0.40,
             "gamma": 0.02, "theta": -0.06, "vega": 0.12, "mid_iv": 0.30},
            {"symbol": "C", "option_type": "call", "strike": 102, "bid": 1.0,
             "ask": 1.2, "open_interest": 100, "volume": 50, "delta": 0.35,
             "gamma": 0.02, "theta": -0.06, "vega": 0.12, "mid_iv": 0.30},
        ])
        monkeypatch.setattr(contracts.tradier, "get_option_expirations",
                            lambda t: ["2024-01-10"])
        monkeypatch.setattr(contracts.tradier, "get_option_chain",
                            lambda t, e: chain)
        c = select_contract("NVDA", "long", 100, 98, 104, today=date(2024, 1, 1))
        assert c is not None
        assert c.symbol == "A"
        assert c.iv_warning is True


# ============================================================
# news.py
# ============================================================

_SAMPLE_XML = """<?xml version="1.0"?>
<weeklyevents>
  <event>
    <title>Non-Farm Employment Change</title>
    <country>USD</country>
    <date>01-05-2024</date>
    <time>8:30am</time>
    <impact>High</impact>
  </event>
  <event>
    <title>Some Low Event</title>
    <country>USD</country>
    <date>01-05-2024</date>
    <time>10:00am</time>
    <impact>Low</impact>
  </event>
  <event>
    <title>EUR Event</title>
    <country>EUR</country>
    <date>01-05-2024</date>
    <time>9:00am</time>
    <impact>High</impact>
  </event>
</weeklyevents>"""


class TestNews:
    def _patch_download(self, monkeypatch):
        monkeypatch.setattr(news, "_download", lambda url: _SAMPLE_XML)
        monkeypatch.setattr(news.cache, "get", lambda *a, **k: None)
        monkeypatch.setattr(news.cache, "set", lambda *a, **k: None)

    def test_fetch_filters_to_high_usd(self, monkeypatch):
        self._patch_download(monkeypatch)
        events = news.fetch_calendar(force=True)
        assert len(events) == 1
        assert events[0].title == "Non-Farm Employment Change"
        assert events[0].country == "USD"
        assert events[0].impact == "High"

    def test_blackout_inside_window(self, monkeypatch):
        self._patch_download(monkeypatch)
        # NFP at 8:30am ET = 13:30 UTC. 1 hour before → blocked (24h before window).
        now = datetime(2024, 1, 5, 12, 30, tzinfo=timezone.utc)
        blocked, ev = news.is_news_blackout(now, before_h=24, after_h=2)
        assert blocked is True
        assert ev is not None and ev.title.startswith("Non-Farm")

    def test_blackout_outside_window(self, monkeypatch):
        self._patch_download(monkeypatch)
        # Two days before → outside the 24h window.
        now = datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc)
        blocked, ev = news.is_news_blackout(now, before_h=24, after_h=2)
        assert blocked is False
        assert ev is None

    def test_blackout_after_window(self, monkeypatch):
        self._patch_download(monkeypatch)
        # 5 hours after the event → past the 2h after-window.
        now = datetime(2024, 1, 5, 18, 30, tzinfo=timezone.utc)
        blocked, _ = news.is_news_blackout(now, before_h=24, after_h=2)
        assert blocked is False

    def test_next_high_impact_event(self, monkeypatch):
        self._patch_download(monkeypatch)
        now = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        ev = news.next_high_impact_event(now)
        assert ev is not None
        assert ev.title.startswith("Non-Farm")

    def test_next_event_none_when_all_past(self, monkeypatch):
        self._patch_download(monkeypatch)
        now = datetime(2024, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert news.next_high_impact_event(now) is None

    def test_json_fallback(self, monkeypatch):
        def _boom(url):
            if url == news.FF_XML_URL:
                raise news.requests.RequestException("xml down")
            return '[{"title":"CPI","country":"USD","impact":"High",' \
                   '"date":"2024-01-05T08:30:00-05:00"}]'
        monkeypatch.setattr(news, "_download", _boom)
        monkeypatch.setattr(news.cache, "get", lambda *a, **k: None)
        monkeypatch.setattr(news.cache, "set", lambda *a, **k: None)
        events = news.fetch_calendar(force=True)
        assert len(events) == 1
        assert events[0].title == "CPI"
