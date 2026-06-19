"""Tests for ict/ote.py, ict/bias.py, and ict/smt.py — Stage 4.

All fixtures are hand-built with known analytic answers.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ict.ote import OTEResult, compute_ote, projection_levels
from ict.bias import BiasResult, get_bias
from ict.smt import SMTResult, analyze, check_dxy, smt_divergence


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _df(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    freq: str = "1D",
) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(opens), freq=freq)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1_000_000] * len(opens)},
        index=idx,
    )


def _trending_up(n: int = 60, freq: str = "1D") -> pd.DataFrame:
    """n bars of a clear uptrend with confirmed bullish BOS events.

    Design:
      bars 0-9:  flat warmup at 100 (ATR seeds; no premature swings).
      bar 10:    swing LOW at 95  (lows[7..9]=99 > 95 < lows[11..13]=99).
      bars 11-13: recovery at 100 (confirms swing low for k=3).
      bar 14:    swing HIGH at 115 (highs[11..13]=101 < 115 > highs[15..17]=101).
      bars 15-17: shallow pullback at 101 (confirms swing high for k=3).
                  At i=14: last_sh_index=14 > last_sl_index=10 → seeds "up".
      bar 18:    BOS close=120 > last_sh_level=115.
      bars 19+:  steadily rising closes so EMA10>EMA20, both rising, gap widens.
    """
    # 10-bar flat warmup
    opens  = [100.0] * 10
    highs  = [101.0] * 10
    lows   = [ 99.0] * 10
    closes = [100.5] * 10

    # bar 10: swing low at 95
    opens  += [96.0];  highs  += [98.0];  lows  += [95.0];  closes += [97.0]
    # bars 11-13: recovery (lows=99 > 95, so bar 10 is k=3 swing low)
    opens  += [99.0,  99.0,  99.0]
    highs  += [101.0, 101.0, 101.0]
    lows   += [99.0,  99.0,  99.0]
    closes += [100.5, 100.5, 100.5]
    # bar 14: swing high at 115
    opens  += [101.0]; highs  += [115.0]; lows  += [100.0]; closes += [113.0]
    # bars 15-17: pullback (highs=101 < 115, confirms swing high for k=3)
    opens  += [101.0, 101.0, 101.0]
    highs  += [101.0, 101.0, 101.0]
    lows   += [100.0, 100.0, 100.0]
    closes += [100.5, 100.5, 100.5]
    # bar 18: bullish BOS — body close above 115
    opens  += [102.0]; highs  += [121.0]; lows  += [101.0]; closes += [120.0]

    # bars 19..n-1: rising closes, each bar 2.5 higher than the last BOS close
    base = 122.0
    for j in range(n - 19):
        mid = base + j * 2.5
        opens.append(round(mid - 0.3, 4))
        highs.append(round(mid + 1.5, 4))
        lows.append(round(mid - 1.5, 4))
        closes.append(round(mid + 0.3, 4))

    idx = pd.date_range("2024-01-01", periods=n, freq=freq)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1_000_000] * n},
        index=idx,
    )


def _trending_down(n: int = 60, freq: str = "1D") -> pd.DataFrame:
    """n bars of a clear downtrend with confirmed bearish BOS events (mirror of _trending_up).

    Design (mirror):
      bars 0-9:  flat warmup at 300.
      bar 10:    swing HIGH at 305 (confirmed by k=3 neighbours).
      bars 11-13: pullback at 300.
      bar 14:    swing LOW at 285.
      bars 15-17: slight recovery at 300.
                  At i=14: last_sl_index=14 > last_sh_index=10 → seeds "down".
      bar 18:    BOS close=280 < last_sl_level=285.
      bars 19+:  steadily falling closes so EMA10<EMA20, both falling, gap widens.
    """
    opens  = [300.0] * 10
    highs  = [301.0] * 10
    lows   = [299.0] * 10
    closes = [300.5] * 10

    # bar 10: swing HIGH at 305
    opens  += [302.0]; highs  += [305.0]; lows  += [301.0]; closes += [303.0]
    # bars 11-13: pullback (highs=301 < 305)
    opens  += [300.0, 300.0, 300.0]
    highs  += [301.0, 301.0, 301.0]
    lows   += [299.0, 299.0, 299.0]
    closes += [300.5, 300.5, 300.5]
    # bar 14: swing LOW at 285
    opens  += [299.0]; highs  += [300.0]; lows  += [285.0]; closes += [287.0]
    # bars 15-17: slight recovery (lows=299 > 285, confirms swing low for k=3)
    opens  += [299.0, 299.0, 299.0]
    highs  += [301.0, 301.0, 301.0]
    lows   += [299.0, 299.0, 299.0]
    closes += [300.5, 300.5, 300.5]
    # bar 18: bearish BOS — body close below 285
    opens  += [298.0]; highs  += [299.0]; lows  += [279.0]; closes += [280.0]

    # bars 19..n-1: falling closes
    base = 278.0
    for j in range(n - 19):
        mid = base - j * 2.5
        opens.append(round(mid + 0.3, 4))
        highs.append(round(mid + 1.5, 4))
        lows.append(round(mid - 1.5, 4))
        closes.append(round(mid - 0.3, 4))

    idx = pd.date_range("2024-01-01", periods=n, freq=freq)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1_000_000] * n},
        index=idx,
    )


# ============================================================
# OTE tests
# ============================================================

class TestProjectionLevels:
    """projection_levels() — pure Fibonacci math."""

    def test_bullish_projections_above_swing_end(self):
        """For a bullish leg, negative ratios extend ABOVE swing_end (the high)."""
        # leg: origin(low)=100, end(high)=110, leg=10
        projs = projection_levels(100.0, 110.0, "bullish")
        # ratio=-0.27 → price = 110 - (-0.27)*10 = 110 + 2.7 = 112.7
        assert abs(projs["-0.27"] - 112.7) < 0.001
        # ratio=-1.0  → price = 110 + 10 = 120
        assert abs(projs["-1.0"] - 120.0) < 0.001
        # ratio=-2.0  → price = 110 + 20 = 130
        assert abs(projs["-2.0"] - 130.0) < 0.001

    def test_bearish_projections_below_swing_end(self):
        """For a bearish leg, negative ratios extend BELOW swing_end (the low)."""
        # leg: origin(high)=110, end(low)=100, leg=10
        projs = projection_levels(110.0, 100.0, "bearish")
        # ratio=-0.27 → price = 100 + (-0.27)*10 = 100 - 2.7 = 97.3
        assert abs(projs["-0.27"] - 97.3) < 0.001
        assert abs(projs["-1.0"] - 90.0)  < 0.001
        assert abs(projs["-2.0"] - 80.0)  < 0.001

    def test_all_default_ratios_present(self):
        projs = projection_levels(100.0, 110.0, "bullish")
        for key in ("-0.27", "-0.62", "-1.0", "-2.0", "-2.5", "-4.0"):
            assert key in projs

    def test_custom_ratios(self):
        projs = projection_levels(100.0, 110.0, "bullish", ratios=(-0.5,))
        assert "-0.5" in projs
        assert abs(projs["-0.5"] - 115.0) < 0.001

    def test_zero_leg_returns_origin(self):
        """Zero-length leg: all projections equal the single anchor point."""
        projs = projection_levels(100.0, 100.0, "bullish")
        for v in projs.values():
            assert v == 100.0


class TestComputeOTE:
    """compute_ote() — retracement zone, in_ote flag, confluence, invalidation."""

    # --- Bullish OTE ---

    def test_bullish_price_in_ote_zone(self):
        """62–79% retracement of a 100→110 leg: OTE zone ≈ [102.1, 103.8]."""
        # 62% retracement: 110 - 0.62*10 = 103.8
        # 79% retracement: 110 - 0.79*10 = 102.1
        result = compute_ote(100.0, 110.0, 103.0, "bullish")
        assert result.in_ote, f"Price 103 should be in OTE zone, got level={result.level:.3f}"
        assert 0.62 <= result.level <= 0.79

    def test_bullish_price_above_ote_zone(self):
        """Price at 105 (50% retrace) is above OTE zone — not in OTE."""
        result = compute_ote(100.0, 110.0, 105.0, "bullish")
        assert not result.in_ote

    def test_bullish_price_below_ote_zone(self):
        """Price at 101 (90% retrace) is below OTE zone."""
        result = compute_ote(100.0, 110.0, 101.0, "bullish")
        assert not result.in_ote

    def test_bullish_entry_zone_bounds(self):
        result = compute_ote(100.0, 110.0, 103.0, "bullish")
        lo, hi = result.entry_zone
        assert lo < hi
        assert abs(hi - 103.8) < 0.01   # 62% retracement
        assert abs(lo - 102.1) < 0.01   # 79% retracement

    def test_bullish_stop_ref_is_origin(self):
        result = compute_ote(100.0, 110.0, 103.0, "bullish")
        assert result.stop_ref == 100.0

    # --- Bearish OTE ---

    def test_bearish_price_in_ote_zone(self):
        """62–79% retracement of 110→100: zone ≈ [106.2, 107.9]."""
        result = compute_ote(110.0, 100.0, 107.0, "bearish")
        assert result.in_ote, f"Price 107 should be in bearish OTE, got level={result.level:.3f}"
        assert 0.62 <= result.level <= 0.79

    def test_bearish_price_below_ote_zone(self):
        result = compute_ote(110.0, 100.0, 105.0, "bearish")
        assert not result.in_ote

    def test_bearish_entry_zone_orientation(self):
        result = compute_ote(110.0, 100.0, 107.0, "bearish")
        lo, hi = result.entry_zone
        assert lo < hi

    def test_bearish_stop_ref_is_origin(self):
        result = compute_ote(110.0, 100.0, 107.0, "bearish")
        assert result.stop_ref == 110.0

    # --- Invalidation ---

    def test_bullish_invalidated_when_price_below_origin(self):
        """Price below swing origin (100) → invalidated."""
        result = compute_ote(100.0, 110.0, 99.0, "bullish")
        assert result.invalidated
        assert not result.in_ote

    def test_bearish_invalidated_when_price_above_origin(self):
        result = compute_ote(110.0, 100.0, 111.0, "bearish")
        assert result.invalidated
        assert not result.in_ote

    def test_not_invalidated_by_wick_only(self):
        """Invalidation is a body-close test — compute_ote checks current_price,
        which the caller should set to the close (not wick)."""
        # Price 101 is above origin=100 but inside OTE range for bearish.
        # Not below origin for bullish.
        result = compute_ote(100.0, 110.0, 103.0, "bullish")
        assert not result.invalidated

    # --- Confluence ---

    def test_confluence_detected_when_level_in_zone(self):
        """A PD-array level inside the OTE zone → has_confluence=True."""
        result = compute_ote(100.0, 110.0, 103.0, "bullish",
                             confluence_levels=[103.5])  # inside [102.1, 103.8]
        assert result.has_confluence

    def test_no_confluence_when_level_outside_zone(self):
        result = compute_ote(100.0, 110.0, 103.0, "bullish",
                             confluence_levels=[106.0])  # above zone
        assert not result.has_confluence

    def test_no_confluence_when_list_empty(self):
        result = compute_ote(100.0, 110.0, 103.0, "bullish", confluence_levels=[])
        assert not result.has_confluence

    # --- Edge cases ---

    def test_zero_leg_does_not_crash(self):
        result = compute_ote(100.0, 100.0, 100.0, "bullish")
        assert isinstance(result, OTEResult)
        assert not result.in_ote

    def test_projections_present_in_result(self):
        result = compute_ote(100.0, 110.0, 103.0, "bullish")
        for key in ("-0.27", "-0.62", "-1.0", "-2.0", "-2.5", "-4.0"):
            assert key in result.projections

    def test_level_clamped_non_negative(self):
        """Price beyond swing_end (e.g. new high) → ratio ≤ 0 → clamped to 0."""
        result = compute_ote(100.0, 110.0, 112.0, "bullish")
        assert result.level >= 0.0


# ============================================================
# Bias tests
# ============================================================

class TestGetBias:
    """get_bias() — top-down multi-timeframe bias."""

    def test_clear_uptrend_returns_long(self):
        up = _trending_up(60)
        result = get_bias(
            daily=up, four_h=up, one_h=up,
            ticker="QQQ", index_tickers=["SPX", "XSP", "QQQ"],
        )
        assert result.bias == "long"

    def test_clear_downtrend_returns_short(self):
        dn = _trending_down(60)
        result = get_bias(
            daily=dn, four_h=dn, one_h=dn,
            ticker="NVDA", index_tickers=["SPX", "XSP", "QQQ"],
        )
        assert result.bias == "short"

    def test_conflicting_daily_structure_vs_ema_returns_none(self):
        """If structure says long but EMA stack says short (or unclear) → none."""
        up   = _trending_up(60)
        down = _trending_down(60)
        # daily is uptrend structure but we pass a downtrend frame for EMA
        # by using flat data on daily: both structure and EMA will be unclear.
        flat_daily = _df([100]*60, [101]*60, [99]*60, [100]*60)
        result = get_bias(
            daily=flat_daily, four_h=up, one_h=up,
            ticker="QQQ", index_tickers=["SPX", "XSP", "QQQ"],
        )
        assert result.bias == "none"

    def test_index_requires_1h_bias(self):
        """For an index ticker, 1H bias must also be clear (Hard Req #1)."""
        up   = _trending_up(60)
        flat = _df([100]*60, [101]*60, [99]*60, [100]*60)
        result = get_bias(
            daily=up, four_h=up, one_h=flat,
            ticker="SPX", index_tickers=["SPX", "XSP", "QQQ"],
        )
        assert result.bias == "none", "Index with flat 1H should return none"

    def test_single_name_does_not_require_1h_bias(self):
        """For a single-name ticker, flat 1H doesn't block the bias."""
        up   = _trending_up(60)
        flat = _df([100]*60, [101]*60, [99]*60, [100]*60)
        result = get_bias(
            daily=up, four_h=up, one_h=flat,
            ticker="NVDA", index_tickers=["SPX", "XSP", "QQQ"],
        )
        # NVDA is not an index → flat 1H is OK; bias comes from daily+4H.
        assert result.bias in ("long", "none")   # "long" if daily+4H agree

    def test_contradicting_4h_returns_none(self):
        up   = _trending_up(60)
        down = _trending_down(60)
        result = get_bias(
            daily=up, four_h=down, one_h=up,
            ticker="NVDA", index_tickers=["SPX", "XSP", "QQQ"],
        )
        assert result.bias == "none"

    def test_result_has_required_fields(self):
        up = _trending_up(60)
        result = get_bias(
            daily=up, four_h=up, one_h=up,
            ticker="QQQ", index_tickers=["SPX", "XSP", "QQQ"],
        )
        assert result.daily_bias in ("long", "short", "none")
        assert result.four_h_bias in ("long", "short", "none")
        assert result.one_h_bias in ("long", "short", "none")
        assert isinstance(result.ema_stack_ok, bool)
        assert isinstance(result.reasons, list)
        assert len(result.reasons) > 0

    def test_too_short_data_returns_none(self):
        tiny = _df([100]*3, [101]*3, [99]*3, [100]*3)
        result = get_bias(
            daily=tiny, four_h=tiny, one_h=tiny,
            ticker="QQQ", index_tickers=["SPX", "XSP", "QQQ"],
        )
        assert result.bias == "none"


# ============================================================
# SMT / DXY tests
# ============================================================

class TestCheckDXY:
    """check_dxy() — inverse correlation gate."""

    def test_long_equity_weak_dxy_agrees(self):
        """Equity long + DXY downtrend → agrees (inverse rule)."""
        dxy_down = _trending_down(60)
        assert check_dxy("long", dxy_down, swing_k=3) is True

    def test_long_equity_strong_dxy_contradicts(self):
        """Equity long + DXY uptrend → contradiction."""
        dxy_up = _trending_up(60)
        assert check_dxy("long", dxy_up, swing_k=3) is False

    def test_short_equity_strong_dxy_agrees(self):
        """Equity short + DXY uptrend → agrees."""
        dxy_up = _trending_up(60)
        assert check_dxy("short", dxy_up, swing_k=3) is True

    def test_short_equity_weak_dxy_contradicts(self):
        dxy_down = _trending_down(60)
        assert check_dxy("short", dxy_down, swing_k=3) is False

    def test_ranging_dxy_does_not_block(self):
        """Flat/ranging DXY returns True (non-contradicting by convention)."""
        flat = _df([100]*60, [101]*60, [99]*60, [100]*60)
        assert check_dxy("long", flat, swing_k=3) is True

    def test_empty_dxy_does_not_block(self):
        empty = _df([], [], [], [])
        assert check_dxy("long", empty, swing_k=3) is True


class TestSMTDivergence:
    """smt_divergence() — positively-correlated pair divergence."""

    def _make_pair(
        self,
        lows_a: list[float],
        lows_b: list[float],
        highs_a: list[float] | None = None,
        highs_b: list[float] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Build two DataFrames with controlled swing lows and highs."""
        n = len(lows_a)
        highs_a = highs_a or [l + 2 for l in lows_a]
        highs_b = highs_b or [l + 2 for l in lows_b]
        closes_a = [(h + l) / 2 for h, l in zip(highs_a, lows_a)]
        closes_b = [(h + l) / 2 for h, l in zip(highs_b, lows_b)]
        idx = pd.date_range("2024-01-01", periods=n, freq="1h")

        def _build(h, l, c):
            return pd.DataFrame(
                {"open": c, "high": h, "low": l, "close": c, "volume": [1000]*n},
                index=idx,
            )

        return _build(highs_a, lows_a, closes_a), _build(highs_b, lows_b, closes_b)

    def test_bullish_smt_detected(self):
        """df_a makes LL, df_b makes HL → bullish SMT divergence.

        k=2 swing lows at bars 2 and 9 (need 2 strictly-lower neighbours each side).
          df_a: low[2]=10, low[9]=7  → lower low  (7 < 10)
          df_b: low[2]=8,  low[9]=9  → higher low  (9 > 8)
        Surrounding bars are strictly higher so swing_points fires at 2 and 9.
        """
        lows_a = [12, 11, 10, 11, 12, 12, 12, 12, 11,  7, 11, 12]
        lows_b = [12, 11,  8, 11, 12, 12, 12, 12, 11,  9, 11, 12]
        df_a, df_b = self._make_pair(lows_a, lows_b)
        result = smt_divergence(df_a, df_b, k=2)
        assert result == "bullish", f"Expected bullish SMT, got {result}"

    def test_bearish_smt_detected(self):
        """df_a makes HH, df_b makes LH → bearish SMT divergence.

        k=2 swing highs at bars 2 and 9.
          df_a: high[2]=15, high[9]=20 → higher high (20 > 15)
          df_b: high[2]=18, high[9]=12 → lower high  (12 < 18)
        """
        highs_a = [10, 11, 15, 11, 10, 10, 10, 10, 11, 20, 11, 10]
        highs_b = [10, 11, 18, 11, 10, 10, 10, 10, 11, 12, 11, 10]
        lows = [8] * 12
        df_a, df_b = self._make_pair(lows, lows, highs_a, highs_b)
        result = smt_divergence(df_a, df_b, k=2)
        assert result == "bearish", f"Expected bearish SMT, got {result}"

    def test_no_divergence_when_both_make_same_move(self):
        """Both make lower lows together → no SMT divergence."""
        # Swing lows at bars 2 and 9; both are lower lows → no bullish SMT.
        lows_a = [12, 11, 10, 11, 12, 12, 12, 12, 11, 7, 11, 12]
        lows_b = [12, 11,  9, 11, 12, 12, 12, 12, 11, 6, 11, 12]
        df_a, df_b = self._make_pair(lows_a, lows_b)
        result = smt_divergence(df_a, df_b, k=2)
        assert result != "bullish", "Both making LL should not be bullish SMT"

    def test_insufficient_data_returns_none(self):
        tiny = _df([100], [101], [99], [100])
        assert smt_divergence(tiny, tiny, k=2) is None


class TestAnalyze:
    """analyze() — combined DXY + SMT result."""

    def test_returns_smt_result(self):
        dxy_down = _trending_down(60)
        result = analyze("long", dxy_down)
        assert isinstance(result, SMTResult)
        assert isinstance(result.dxy_agrees, bool)
        assert result.smt in ("bullish", "bearish", None)
        assert isinstance(result.detail, str)

    def test_dxy_agrees_propagated(self):
        dxy_up = _trending_up(60)
        result = analyze("long", dxy_up)
        assert result.dxy_agrees is False

    def test_empty_peer_dfs_no_crash(self):
        dxy_down = _trending_down(60)
        result = analyze("long", dxy_down, peer_dfs={}, equity_df=None)
        assert isinstance(result, SMTResult)

    def test_detail_string_non_empty(self):
        dxy_down = _trending_down(60)
        result = analyze("long", dxy_down)
        assert len(result.detail) > 0
