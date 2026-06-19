"""Tests for ict/liquidity.py — Stage 3.

Covers:
  - Pool detection: swing H/L, equal highs/lows, PDH/PDL.
  - Sweep detection: BSL and SSL sweeps (wick beyond + reversal close).
  - Wick-only case that must NOT register as a sweep (close doesn't return).
  - latest_sweep filtering.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ict.liquidity import (
    LiquidityPool,
    detect_sweeps,
    find_liquidity_pools,
    latest_sweep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    freq: str = "1h",
) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02 09:30", periods=len(opens), freq=freq)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1000] * len(opens)},
        index=idx,
    )


def _flat(n: int, mid: float = 100.0, spread: float = 1.0, freq: str = "1h") -> pd.DataFrame:
    return _df(
        [mid] * n, [mid + spread] * n, [mid - spread] * n, [mid] * n, freq=freq,
    )


# ---------------------------------------------------------------------------
# Pool detection
# ---------------------------------------------------------------------------

class TestFindLiquidityPools:
    def test_swing_high_creates_bsl_pool(self):
        """A clear isolated swing high should produce a BSL pool."""
        highs = [10.0] * 10
        lows = [9.0] * 10
        highs[5] = 15.0
        lows[5] = 9.5
        df = _df([10] * 10, highs, lows, [(h + l) / 2 for h, l in zip(highs, lows)])
        pools = find_liquidity_pools(df, k=2)
        bsl = [p for p in pools if p.side == "BSL" and p.source == "swing_high"]
        assert bsl, "Expected a BSL pool at the swing high"
        assert any(abs(p.pool_level - 15.0) < 0.01 for p in bsl)

    def test_swing_low_creates_ssl_pool(self):
        highs = [10.0] * 10
        lows = [9.0] * 10
        lows[5] = 5.0
        highs[5] = 9.5
        df = _df([10] * 10, highs, lows, [(h + l) / 2 for h, l in zip(highs, lows)])
        pools = find_liquidity_pools(df, k=2)
        ssl = [p for p in pools if p.side == "SSL" and p.source == "swing_low"]
        assert ssl, "Expected an SSL pool at the swing low"
        assert any(abs(p.pool_level - 5.0) < 0.01 for p in ssl)

    def test_equal_highs_detected(self):
        """Two swing highs within ATR tolerance → equal_highs BSL pool."""
        highs = [10.0] * 20
        lows = [9.0] * 20
        highs[5] = 15.0
        highs[14] = 15.05   # very close to the first → equal
        df = _df(
            [10.0] * 20, highs, lows,
            [(h + l) / 2 for h, l in zip(highs, lows)],
        )
        pools = find_liquidity_pools(df, k=2, equal_tol_atr=0.5, atr_length=14)
        eq = [p for p in pools if p.source == "equal_highs"]
        assert eq, "Expected an equal_highs pool"

    def test_equal_lows_detected(self):
        highs = [10.0] * 20
        lows = [9.0] * 20
        lows[5] = 5.0
        lows[14] = 5.02
        df = _df(
            [10.0] * 20, highs, lows,
            [(h + l) / 2 for h, l in zip(highs, lows)],
        )
        pools = find_liquidity_pools(df, k=2, equal_tol_atr=0.5, atr_length=14)
        eq = [p for p in pools if p.source == "equal_lows"]
        assert eq, "Expected an equal_lows pool"

    def test_empty_df_returns_empty(self):
        df = _flat(0)
        assert find_liquidity_pools(df) == []

    def test_all_pools_have_required_fields(self):
        highs = [10.0] * 10
        lows = [9.0] * 10
        highs[5] = 15.0
        df = _df([10] * 10, highs, lows, [(h + l) / 2 for h, l in zip(highs, lows)])
        for pool in find_liquidity_pools(df):
            assert pool.side in ("BSL", "SSL")
            assert isinstance(pool.pool_level, float)
            assert isinstance(pool.formed_index, int)

    def test_pdh_pdl_detected_from_intraday(self):
        """Multi-day intraday data should surface PDH/PDL pools."""
        # Two full days at 1H frequency.
        day1 = _flat(7, mid=100.0, spread=5.0, freq="1h")
        day2_idx = pd.date_range("2024-01-03 09:30", periods=7, freq="1h")
        day2 = day1.copy()
        day2.index = day2_idx
        df = pd.concat([day1, day2])
        pools = find_liquidity_pools(df)
        pdh = [p for p in pools if p.source == "PDH"]
        pdl = [p for p in pools if p.source == "PDL"]
        assert pdh, "Expected PDH pool from prior day"
        assert pdl, "Expected PDL pool from prior day"


# ---------------------------------------------------------------------------
# Sweep detection
# ---------------------------------------------------------------------------

class TestDetectSweeps:
    def _bsl_pool(self, level: float, formed: int = 2) -> LiquidityPool:
        return LiquidityPool(pool_level=level, side="BSL", source="swing_high", formed_index=formed)

    def _ssl_pool(self, level: float, formed: int = 2) -> LiquidityPool:
        return LiquidityPool(pool_level=level, side="SSL", source="swing_low", formed_index=formed)

    def test_bsl_sweep_detected(self):
        """Wick above the BSL level then close BACK below it → sweep."""
        level = 110.0
        # Bar 0-2: below level. Bar 3: wick above (high=115), close below (close=108).
        opens  = [100, 101, 102, 106]
        highs  = [102, 103, 104, 115]   # bar3 wicks above 110
        lows   = [ 99,  99, 100, 105]
        closes = [101, 102, 103, 108]   # bar3 closes below 110
        df = _df(opens, highs, lows, closes)
        pool = self._bsl_pool(level, formed=0)
        result = detect_sweeps([pool], df, sweep_window=3)
        assert result[0].swept, "BSL pool should be swept when wick > level and close < level"
        assert result[0].sweep_index == 3

    def test_ssl_sweep_detected(self):
        """Wick below SSL level then close BACK above it → sweep."""
        level = 90.0
        opens  = [100,  99,  98,  94]
        highs  = [102, 101, 100,  97]
        lows   = [ 98,  97,  96,  85]   # bar3 wicks below 90
        closes = [ 99,  98,  97,  93]   # bar3 closes above 90
        df = _df(opens, highs, lows, closes)
        pool = self._ssl_pool(level, formed=0)
        result = detect_sweeps([pool], df, sweep_window=3)
        assert result[0].swept, "SSL pool should be swept when wick < level and close > level"
        assert result[0].sweep_index == 3

    def test_wick_only_no_reversal_close_not_a_sweep(self):
        """
        CRITICAL (§8.2): a wick beyond the pool level that does NOT close
        back through the level must NOT register as a sweep.
        """
        level = 110.0
        opens  = [100, 101, 102, 106]
        highs  = [102, 103, 104, 115]   # bar3 wicks above 110
        lows   = [ 99,  99, 100, 105]
        closes = [101, 102, 103, 112]   # bar3 STAYS above 110 — not a sweep
        df = _df(opens, highs, lows, closes)
        pool = self._bsl_pool(level, formed=0)
        result = detect_sweeps([pool], df, sweep_window=3)
        assert not result[0].swept, (
            "Wick-only (no reversal close) must NOT be counted as a sweep (§8.2)"
        )

    def test_sweep_only_after_pool_formed(self):
        """Bars before formed_index should be ignored."""
        level = 110.0
        opens  = [106, 100, 101, 102]
        highs  = [115, 103, 103, 104]   # bar0 wicks above (but pool forms at bar1)
        lows   = [105,  99,  99, 100]
        closes = [108, 102, 102, 103]   # bar0 closes below 110 but before pool
        df = _df(opens, highs, lows, closes)
        pool = self._bsl_pool(level, formed=1)
        result = detect_sweeps([pool], df, sweep_window=3)
        assert not result[0].swept, "Sweep before pool formed must not count"

    def test_no_sweep_when_price_never_reaches_level(self):
        level = 200.0  # far above all bars
        df = _flat(8, mid=100.0)
        pool = self._bsl_pool(level, formed=0)
        result = detect_sweeps([pool], df)
        assert not result[0].swept

    def test_multiple_pools_handled_independently(self):
        bsl_level = 110.0
        ssl_level = 90.0
        opens  = [100, 106,  94]
        highs  = [102, 115,  97]
        lows   = [ 98, 105,  85]
        closes = [101, 108,  93]
        df = _df(opens, highs, lows, closes)
        pools = [
            self._bsl_pool(bsl_level, formed=0),
            self._ssl_pool(ssl_level, formed=0),
        ]
        results = detect_sweeps(pools, df)
        assert results[0].swept   # BSL at 110 swept on bar1
        assert results[1].swept   # SSL at 90 swept on bar2


# ---------------------------------------------------------------------------
# latest_sweep
# ---------------------------------------------------------------------------

class TestLatestSweep:
    def _swept(self, side: str, sweep_idx: int, formed: int = 0) -> LiquidityPool:
        return LiquidityPool(
            pool_level=100.0, side=side, source="swing_high",
            formed_index=formed, swept=True, sweep_index=sweep_idx,
        )

    def _unswept(self, side: str) -> LiquidityPool:
        return LiquidityPool(
            pool_level=100.0, side=side, source="swing_low",
            formed_index=0, swept=False,
        )

    def test_returns_none_when_no_sweeps(self):
        pools = [self._unswept("BSL"), self._unswept("SSL")]
        assert latest_sweep(pools, "BSL") is None

    def test_returns_most_recent_by_sweep_index(self):
        p1 = self._swept("BSL", sweep_idx=3)
        p2 = self._swept("BSL", sweep_idx=7)
        p3 = self._swept("BSL", sweep_idx=5)
        result = latest_sweep([p1, p2, p3], "BSL")
        assert result is p2

    def test_filters_by_side(self):
        bsl = self._swept("BSL", sweep_idx=5)
        ssl = self._swept("SSL", sweep_idx=9)
        assert latest_sweep([bsl, ssl], "BSL") is bsl
        assert latest_sweep([bsl, ssl], "SSL") is ssl

    def test_after_index_filter(self):
        p1 = self._swept("SSL", sweep_idx=2)
        p2 = self._swept("SSL", sweep_idx=8)
        result = latest_sweep([p1, p2], "SSL", after_index=5)
        assert result is p2

    def test_after_index_excludes_all_returns_none(self):
        p = self._swept("BSL", sweep_idx=3)
        assert latest_sweep([p], "BSL", after_index=10) is None
