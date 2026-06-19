"""Tests for ict/primitives.py — Stage 2.

All fixtures are hand-built with known analytic answers so failures are
unambiguous. No network calls; no file I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ict.primitives import atr, dealing_range, displacement, ema, swing_points


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    highs: list[float],
    lows: list[float],
    opens: list[float] | None = None,
    closes: list[float] | None = None,
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from explicit H/L series."""
    n = len(highs)
    closes = closes or [(h + l) / 2 for h, l in zip(highs, lows)]
    opens = opens or closes  # open = close for neutral candles
    volumes = volumes or [1000] * n
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

class TestATR:
    def test_output_length_matches_input(self):
        df = _make_ohlcv([10] * 20, [9] * 20)
        result = atr(df, length=14)
        assert len(result) == len(df)
        assert result.index.equals(df.index)

    def test_constant_bars_atr_equals_range(self):
        """When every bar has high-low=1 and no gaps the ATR converges to 1."""
        highs = [11.0] * 60
        lows = [10.0] * 60
        df = _make_ohlcv(highs, lows, closes=[10.5] * 60)
        result = atr(df, length=14)
        # After enough bars the RMA should be within 1 % of 1.0.
        assert abs(float(result.iloc[-1]) - 1.0) < 0.02

    def test_atr_positive(self):
        highs = [100 + i * 0.5 for i in range(30)]
        lows = [99 + i * 0.5 for i in range(30)]
        df = _make_ohlcv(highs, lows)
        result = atr(df, length=14)
        assert (result.dropna() > 0).all()

    def test_atr_increases_with_volatility(self):
        """A block of calm bars then a block of wide bars → ATR rises."""
        calm = [10.0] * 30
        volatile = [15.0] * 30
        calm_l = [9.5] * 30
        volatile_l = [9.0] * 30
        highs = calm + volatile
        lows = calm_l + volatile_l
        df = _make_ohlcv(highs, lows)
        result = atr(df, length=14)
        assert float(result.iloc[-1]) > float(result.iloc[25])

    def test_atr_respects_length_param(self):
        """A shorter length should respond faster to a volatility spike."""
        highs = [10.0] * 20 + [20.0] * 5
        lows = [9.5] * 20 + [19.0] * 5
        df = _make_ohlcv(highs, lows)
        fast = atr(df, length=3)
        slow = atr(df, length=14)
        assert float(fast.iloc[-1]) > float(slow.iloc[-1])

    def test_atr_single_bar_returns_series(self):
        df = _make_ohlcv([10], [9])
        result = atr(df, length=14)
        assert isinstance(result, pd.Series)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Swing points
# ---------------------------------------------------------------------------

class TestSwingPoints:
    def _flat_with_peak(self, peak_idx: int = 5, n: int = 12) -> pd.DataFrame:
        """Flat highs=10/lows=9 everywhere except a clear peak at peak_idx."""
        highs = [10.0] * n
        lows = [9.0] * n
        highs[peak_idx] = 15.0
        lows[peak_idx] = 9.5
        return _make_ohlcv(highs, lows)

    def _flat_with_trough(self, trough_idx: int = 5, n: int = 12) -> pd.DataFrame:
        highs = [10.0] * n
        lows = [9.0] * n
        lows[trough_idx] = 5.0
        highs[trough_idx] = 9.5
        return _make_ohlcv(highs, lows)

    # --- swing high ---

    def test_swing_high_detected_at_peak(self):
        df = self._flat_with_peak(peak_idx=5)
        sh, _ = swing_points(df, k=2)
        assert sh.iloc[5], "Expected swing high at peak index 5"

    def test_no_swing_high_at_non_peak(self):
        df = self._flat_with_peak(peak_idx=5)
        sh, _ = swing_points(df, k=2)
        non_peak = sh.copy()
        non_peak.iloc[5] = False
        assert not non_peak.any(), "No other bars should be swing highs"

    def test_swing_high_requires_strict_greater(self):
        """Equal neighbours must NOT qualify as a swing high."""
        highs = [10.0] * 10
        df = _make_ohlcv(highs, [9.0] * 10)
        sh, _ = swing_points(df, k=2)
        assert not sh.any()

    def test_swing_high_first_k_bars_false(self):
        df = self._flat_with_peak(peak_idx=5)
        sh, _ = swing_points(df, k=2)
        assert not sh.iloc[:2].any(), "First k bars should always be False"

    def test_swing_high_last_k_bars_false(self):
        df = self._flat_with_peak(peak_idx=5)
        sh, _ = swing_points(df, k=2)
        assert not sh.iloc[-2:].any(), "Last k bars should always be False"

    # --- swing low ---

    def test_swing_low_detected_at_trough(self):
        df = self._flat_with_trough(trough_idx=5)
        _, sl = swing_points(df, k=2)
        assert sl.iloc[5], "Expected swing low at trough index 5"

    def test_no_swing_low_at_non_trough(self):
        df = self._flat_with_trough(trough_idx=5)
        _, sl = swing_points(df, k=2)
        non_trough = sl.copy()
        non_trough.iloc[5] = False
        assert not non_trough.any()

    def test_swing_low_requires_strict_less(self):
        lows = [9.0] * 10
        df = _make_ohlcv([10.0] * 10, lows)
        _, sl = swing_points(df, k=2)
        assert not sl.any()

    # --- k parameter ---

    def test_k3_needs_three_bars_each_side(self):
        """A peak at index 3 with k=3 needs 3 bars before and 3 after."""
        highs = [10.0] * 9
        highs[3] = 15.0
        df = _make_ohlcv(highs, [9.0] * 9)
        sh, _ = swing_points(df, k=3)
        assert sh.iloc[3], "Swing high should be detected at index 3 with k=3"

    def test_k3_near_edge_not_detected(self):
        """With k=3 a peak at index 2 can't have 3 bars before → False."""
        highs = [10.0] * 9
        highs[2] = 15.0
        df = _make_ohlcv(highs, [9.0] * 9)
        sh, _ = swing_points(df, k=3)
        assert not sh.iloc[2]

    # --- return types ---

    def test_returns_boolean_series(self):
        df = self._flat_with_peak()
        sh, sl = swing_points(df, k=2)
        assert sh.dtype == bool
        assert sl.dtype == bool

    def test_index_aligned_to_df(self):
        df = self._flat_with_peak()
        sh, sl = swing_points(df, k=2)
        assert sh.index.equals(df.index)
        assert sl.index.equals(df.index)

    def test_multiple_swings_detected(self):
        """Two separate peaks in one series — both should be detected."""
        highs = [10.0] * 20
        lows = [9.0] * 20
        highs[5] = 15.0
        highs[14] = 16.0
        df = _make_ohlcv(highs, lows)
        sh, _ = swing_points(df, k=2)
        assert sh.iloc[5] and sh.iloc[14]


# ---------------------------------------------------------------------------
# Displacement
# ---------------------------------------------------------------------------

class TestDisplacement:
    def _df_with_body(self, bodies: list[float], atr_val: float = 1.0) -> pd.DataFrame:
        """Construct a DataFrame where each candle has the given body size.

        ATR (Wilder) is forced to atr_val by giving all bars high-low=atr_val
        and neutral wicks. Displacement uses shift(1) so we pad the front.
        """
        n = len(bodies)
        opens = [100.0] * n
        closes = [o + b for o, b in zip(opens, bodies)]
        highs = [max(o, c) + atr_val / 2 for o, c in zip(opens, closes)]
        lows = [min(o, c) - atr_val / 2 for o, c in zip(opens, closes)]
        return _make_ohlcv(highs, lows, opens=opens, closes=closes)

    def test_large_body_is_displacement(self):
        """A candle with body = 3*ATR should be displacement (mult=1.5)."""
        # pad 15 bars of ATR=1 body=0.5 (calm), then spike
        calm = [0.5] * 20
        spike = [3.0]
        df = self._df_with_body(calm + spike, atr_val=1.0)
        d = displacement(df, atr_length=10, mult=1.5)
        assert d.iloc[-1], "Body 3x ATR should be displacement"

    def test_small_body_is_not_displacement(self):
        """A candle with body = 0.5*ATR is NOT displacement."""
        small = [0.5] * 25
        df = self._df_with_body(small, atr_val=1.0)
        d = displacement(df, atr_length=10, mult=1.5)
        assert not d.iloc[-1], "Body 0.5x ATR should not be displacement"

    def test_returns_boolean_series(self):
        df = self._df_with_body([1.0] * 20)
        d = displacement(df)
        assert d.dtype == bool

    def test_index_aligned_to_df(self):
        df = self._df_with_body([1.0] * 20)
        d = displacement(df)
        assert d.index.equals(df.index)

    def test_length_equals_input(self):
        df = self._df_with_body([1.0] * 20)
        d = displacement(df)
        assert len(d) == len(df)

    def test_mult_parameter_respected(self):
        """Raising mult from 1.5 to 4.0 should turn a previously-True bar False."""
        calm = [0.5] * 20
        moderate = [2.5]  # 2.5x ATR — True at mult=1.5, False at mult=4.0
        df = self._df_with_body(calm + moderate, atr_val=1.0)
        assert displacement(df, atr_length=10, mult=1.5).iloc[-1]
        assert not displacement(df, atr_length=10, mult=4.0).iloc[-1]

    def test_negative_body_displacement(self):
        """Bearish candle with large body should also qualify."""
        calm = [0.5] * 20
        spike = [-3.0]  # bearish 3x ATR
        df = self._df_with_body(calm + spike, atr_val=1.0)
        d = displacement(df, atr_length=10, mult=1.5)
        assert d.iloc[-1], "Bearish 3x ATR body should be displacement"


# ---------------------------------------------------------------------------
# Dealing range
# ---------------------------------------------------------------------------

class TestDealingRange:
    def _range_df(self, low: float = 90.0, high: float = 110.0, n: int = 20) -> pd.DataFrame:
        """Flat frame with one confirmed swing low and one confirmed swing high."""
        highs = [100.0] * n
        lows = [99.0] * n
        # Place clear peak and trough well inside so k=2 can see both sides.
        highs[n // 3] = high
        lows[n // 3] = high - 1
        lows[2 * n // 3] = low
        highs[2 * n // 3] = low + 1
        return _make_ohlcv(highs, lows)

    def test_equilibrium_midpoint(self):
        df = self._range_df(low=90.0, high=110.0)
        dr = dealing_range(df, lookback=20)
        assert abs(dr["equilibrium"] - 100.0) < 0.01

    def test_range_low_less_than_range_high(self):
        df = self._range_df(low=90.0, high=110.0)
        dr = dealing_range(df, lookback=20)
        assert dr["range_low"] < dr["range_high"]

    def test_expected_keys_present(self):
        df = self._range_df()
        dr = dealing_range(df, lookback=20)
        for key in ("range_low", "range_high", "equilibrium",
                    "premium_threshold", "discount_threshold"):
            assert key in dr, f"Missing key: {key}"

    def test_premium_and_discount_equal_equilibrium(self):
        """premium_threshold == discount_threshold == equilibrium by spec."""
        df = self._range_df()
        dr = dealing_range(df, lookback=20)
        assert dr["premium_threshold"] == dr["equilibrium"]
        assert dr["discount_threshold"] == dr["equilibrium"]

    def test_raises_on_insufficient_data(self):
        """Fewer bars than lookback with no swing points → ValueError."""
        df = _make_ohlcv([10.0] * 3, [9.0] * 3)
        with pytest.raises(ValueError):
            dealing_range(df, lookback=50)

    def test_lookback_limits_search_window(self):
        """A swing point outside the lookback window must not be used."""
        highs = [15.0] + [10.0] * 30
        lows = [8.0] + [9.0] * 30
        df = _make_ohlcv(highs, lows)
        # lookback=10 should not see the swing at index 0 (31 bars total)
        # If only flat bars in window → ValueError expected.
        with pytest.raises(ValueError):
            dealing_range(df, lookback=10)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEMA:
    def test_output_length_matches_input(self):
        s = pd.Series([float(i) for i in range(30)])
        result = ema(s, 10)
        assert len(result) == 30

    def test_ema_of_constant_series_equals_constant(self):
        s = pd.Series([5.0] * 50)
        result = ema(s, 10)
        assert (result - 5.0).abs().max() < 1e-10

    def test_ema_lags_raw_series_on_ramp(self):
        """On a rising ramp EMA should be below the current price."""
        s = pd.Series([float(i) for i in range(50)])
        result = ema(s, 10)
        assert float(result.iloc[-1]) < float(s.iloc[-1])

    def test_fast_ema_reacts_faster_than_slow(self):
        """After a jump from 0→100, the fast EMA should be higher than slow."""
        s = pd.Series([0.0] * 20 + [100.0] * 20)
        fast = ema(s, 5)
        slow = ema(s, 20)
        assert float(fast.iloc[-1]) > float(slow.iloc[-1])

    def test_ema_returns_series_with_matching_index(self):
        idx = pd.date_range("2024-01-01", periods=20, freq="1D")
        s = pd.Series(range(20), index=idx, dtype=float)
        result = ema(s, 5)
        assert result.index.equals(idx)

    def test_ema_span1_equals_original(self):
        """EMA with span=1 is just the series itself (alpha=1 → instant decay)."""
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(s, 1)
        pd.testing.assert_series_equal(result, s, check_names=False)
