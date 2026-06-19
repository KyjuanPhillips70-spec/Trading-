"""End-to-end pipeline tests — Stage 6.

The analysis core (scanner.evaluate) is exercised with hand-built frames and
monkeypatched sub-analyses so each gate can be checked in isolation, plus one
full pass that produces a Setup. No network is touched.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

import scanner
from alert import Setup
from contracts import Contract
from ict.bias import BiasResult
from ict.liquidity import LiquidityPool
from ict.ote import OTEResult
from ict.smt import SMTResult
from ict.structure import StructureEvent
from risk import RiskSetup
from scanner import TickerData, _confidence_score, evaluate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ohlcv(n: int, base: float = 100.0, freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq=freq)
    return pd.DataFrame(
        {"open": [base] * n, "high": [base + 1] * n,
         "low": [base - 1] * n, "close": [base] * n, "volume": [1000] * n},
        index=idx,
    )


def _flat_data() -> TickerData:
    daily = _ohlcv(60, freq="1D")
    ltf = _ohlcv(40, freq="1h")
    return TickerData(daily=daily, four_h=ltf, one_h=ltf, fifteen_m=ltf,
                      dxy=_ohlcv(60, freq="1D"), peers={})


def _contract() -> Contract:
    return Contract(
        symbol="NVDA240119C00500000", option_type="call", strike=500.0,
        expiry=date(2024, 1, 19), dte=10, bid=4.9, ask=5.1, mid=5.0,
        delta=0.55, theta=-0.05, gamma=0.01, vega=0.1, iv=0.45,
        oi=1000, volume=300, settlement_note="equity",
    )


def _patch_full_pass(monkeypatch):
    """Monkeypatch every sub-analysis so evaluate() reaches a Setup."""
    monkeypatch.setattr(scanner, "get_bias", lambda **kw: BiasResult(
        bias="long", htf_zone=None, reasons=["ok"],
        daily_bias="long", four_h_bias="long", one_h_bias="long", ema_stack_ok=True,
    ))
    monkeypatch.setattr(scanner, "smt_analyze", lambda **kw: SMTResult(
        dxy_agrees=True, smt="bullish", detail="ok",
    ))
    ssl = LiquidityPool(pool_level=99.0, side="SSL", source="swing_low",
                        formed_index=5, swept=True, sweep_index=10)
    bsl = LiquidityPool(pool_level=110.0, side="BSL", source="swing_high",
                        formed_index=6, swept=False)
    monkeypatch.setattr(scanner, "find_liquidity_pools", lambda *a, **k: [ssl, bsl])
    monkeypatch.setattr(scanner, "detect_sweeps", lambda pools, *a, **k: pools)
    monkeypatch.setattr(scanner, "detect_structure", lambda *a, **k: [
        StructureEvent(type="BOS", direction="bullish", break_level=105.0,
                       index=15, displacement=True),
    ])
    monkeypatch.setattr(scanner, "find_fvgs", lambda *a, **k: [])
    monkeypatch.setattr(scanner, "find_order_blocks", lambda *a, **k: [])
    monkeypatch.setattr(scanner, "compute_ote", lambda **kw: OTEResult(
        in_ote=True, level=0.705, entry_zone=(99.0, 101.0), stop_ref=99.0,
        projections={}, has_confluence=True, invalidated=False,
    ))
    monkeypatch.setattr(scanner, "is_news_blackout", lambda *a, **k: (False, None))
    monkeypatch.setattr(scanner, "next_high_impact_event", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "compute_risk", lambda **kw: RiskSetup(
        entry=100.0, stop=98.0, target=102.0, risk=2.0, reward=2.0, rr=1.0,
        option_debit=5.0, option_gain=110.0, option_loss=-110.0,
    ))
    monkeypatch.setattr(scanner, "select_contract", lambda **kw: _contract())


# ---------------------------------------------------------------------------
# _confidence_score
# ---------------------------------------------------------------------------

class TestConfidenceScore:
    def test_all_factors(self):
        assert _confidence_score(True, True, "bullish", True, True) == 100

    def test_none(self):
        assert _confidence_score(False, False, None, False, False) == 0

    def test_bias_and_sweep_only(self):
        assert _confidence_score(True, False, None, False, True) == 60

    def test_smt_absent_drops_ten(self):
        assert _confidence_score(True, True, None, True, True) == 90


# ---------------------------------------------------------------------------
# evaluate() — gates
# ---------------------------------------------------------------------------

class TestEvaluateGates:
    def test_no_bias_returns_none(self, monkeypatch):
        monkeypatch.setattr(scanner, "get_bias", lambda **kw: BiasResult(
            bias="none", htf_zone=None, reasons=["flat"]))
        assert evaluate("NVDA", _flat_data()) is None

    def test_dxy_block_returns_none(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        monkeypatch.setattr(scanner, "smt_analyze", lambda **kw: SMTResult(
            dxy_agrees=False, smt=None, detail="contradicts"))
        monkeypatch.setattr(scanner.config, "DXY_MODE", "block")
        assert evaluate("NVDA", _flat_data()) is None

    def test_dxy_warn_does_not_block(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        monkeypatch.setattr(scanner, "smt_analyze", lambda **kw: SMTResult(
            dxy_agrees=False, smt="bullish", detail="warn"))
        monkeypatch.setattr(scanner.config, "DXY_MODE", "warn")
        setup = evaluate("NVDA", _flat_data())
        assert setup is not None
        assert setup.dxy_agrees is False

    def test_no_sweep_returns_none(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        monkeypatch.setattr(scanner, "find_liquidity_pools", lambda *a, **k: [])
        monkeypatch.setattr(scanner, "detect_sweeps", lambda pools, *a, **k: pools)
        assert evaluate("NVDA", _flat_data()) is None

    def test_no_structure_returns_none(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        monkeypatch.setattr(scanner, "detect_structure", lambda *a, **k: [])
        assert evaluate("NVDA", _flat_data()) is None

    def test_news_blackout_returns_none(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        from news import NewsEvent
        ev = NewsEvent("NFP", "USD", "High", datetime(2024, 1, 5, tzinfo=timezone.utc))
        monkeypatch.setattr(scanner, "is_news_blackout", lambda *a, **k: (True, ev))
        assert evaluate("NVDA", _flat_data()) is None

    def test_risk_none_returns_none(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        monkeypatch.setattr(scanner, "compute_risk", lambda **kw: None)
        assert evaluate("NVDA", _flat_data()) is None

    def test_no_contract_returns_none(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        monkeypatch.setattr(scanner, "select_contract", lambda **kw: None)
        assert evaluate("NVDA", _flat_data()) is None


# ---------------------------------------------------------------------------
# evaluate() — full pass
# ---------------------------------------------------------------------------

class TestEvaluateFullPass:
    def test_returns_setup(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        setup = evaluate("NVDA", _flat_data(),
                         now=datetime(2024, 1, 1, tzinfo=timezone.utc),
                         today=date(2024, 1, 1))
        assert isinstance(setup, Setup)
        assert setup.ticker == "NVDA"
        assert setup.direction == "LONG"
        assert setup.sweep_side == "SSL"
        assert setup.structure_event == "BOS"
        assert setup.rr >= 1.0
        assert setup.contract.symbol.startswith("NVDA")
        assert setup.news_clear is True

    def test_short_direction(self, monkeypatch):
        _patch_full_pass(monkeypatch)
        monkeypatch.setattr(scanner, "get_bias", lambda **kw: BiasResult(
            bias="short", htf_zone=None, reasons=["ok"],
            daily_bias="short", four_h_bias="short", one_h_bias="short",
            ema_stack_ok=True))
        monkeypatch.setattr(scanner, "detect_structure", lambda *a, **k: [
            StructureEvent(type="MSS", direction="bearish", break_level=95.0,
                           index=15, displacement=True)])
        # Short needs a swept BSL pool (and an unswept SSL pool below as target).
        bsl = LiquidityPool(pool_level=101.0, side="BSL", source="swing_high",
                            formed_index=5, swept=True, sweep_index=10)
        ssl = LiquidityPool(pool_level=90.0, side="SSL", source="swing_low",
                            formed_index=6, swept=False)
        monkeypatch.setattr(scanner, "find_liquidity_pools", lambda *a, **k: [bsl, ssl])
        setup = evaluate("NVDA", _flat_data())
        assert setup is not None
        assert setup.direction == "SHORT"
        assert setup.sweep_side == "BSL"

    def test_setup_formats_as_alert(self, monkeypatch):
        """A produced Setup must render through the alert formatter."""
        from alert import format_alert
        _patch_full_pass(monkeypatch)
        setup = evaluate("NVDA", _flat_data())
        assert setup is not None
        text = format_alert(setup)
        assert "ICT SWING SETUP" in text
        assert "NVDA" in text


# ---------------------------------------------------------------------------
# evaluate() — integration on flat (real sub-analyses, no monkeypatch)
# ---------------------------------------------------------------------------

def test_flat_market_no_trade():
    """Real pipeline on flat data must produce no setup (bias is none)."""
    assert evaluate("NVDA", _flat_data()) is None
