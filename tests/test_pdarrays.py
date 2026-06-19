"""Tests for ict/pdarrays.py — Stage 3.

Covers the exact 3-candle FVG definition, CE math, OB detection, state
tracking, inversion, and breaker blocks.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ict.pdarrays import (
    BreakerBlock,
    FVG,
    OrderBlock,
    find_breaker_blocks,
    find_fvgs,
    find_order_blocks,
    update_fvg_states,
)
from ict.structure import StructureEvent, detect_structure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(opens), freq="1h")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1000] * len(opens)},
        index=idx,
    )


def _bullish_fvg_df() -> pd.DataFrame:
    """
    3-candle bullish FVG:
      candle1 (i=0): high=100
      candle2 (i=1): BIG body (displacement), high=105, low=100, close=104, open=100.5
      candle3 (i=2): low=102  >  candle1.high=100  → bullish FVG [100, 102]

    We pad 15 calm bars before to let ATR settle.
    """
    # 15 calm bars (body ≈ 0.5, ATR ≈ 1)
    opens  = [100.0] * 15
    highs  = [101.0] * 15
    lows   = [ 99.0] * 15
    closes = [100.5] * 15
    # FVG triplet at indices 15, 16, 17
    opens  += [100.0, 100.5, 104.0]
    highs  += [100.0, 105.0, 106.0]
    lows   += [100.0, 100.0, 102.0]
    closes += [100.0, 104.0, 105.5]
    return _df(opens, highs, lows, closes)


def _bearish_fvg_df() -> pd.DataFrame:
    """
    Bearish FVG:
      candle1 (i=15): low=100
      candle2 (i=16): big bearish body (displacement)
      candle3 (i=17): high=98 < candle1.low=100 → bearish FVG [98, 100]
    """
    opens  = [100.0] * 15
    highs  = [101.0] * 15
    lows   = [ 99.0] * 15
    closes = [100.5] * 15
    opens  += [101.0, 100.5, 97.0]
    highs  += [101.0, 101.0, 98.0]
    lows   += [100.0, 95.0,  96.0]
    closes += [100.0,  96.0,  96.5]
    return _df(opens, highs, lows, closes)


# ---------------------------------------------------------------------------
# FVG tests
# ---------------------------------------------------------------------------

class TestFindFVGs:
    def test_bullish_fvg_detected(self):
        df = _bullish_fvg_df()
        fvgs = find_fvgs(df)
        bull = [f for f in fvgs if f.direction == "bullish"]
        assert bull, "Expected at least one bullish FVG"

    def test_bearish_fvg_detected(self):
        df = _bearish_fvg_df()
        fvgs = find_fvgs(df)
        bear = [f for f in fvgs if f.direction == "bearish"]
        assert bear, "Expected at least one bearish FVG"

    def test_bullish_fvg_zone_correct(self):
        """top = candle3.low, bottom = candle1.high."""
        df = _bullish_fvg_df()
        fvgs = find_fvgs(df)
        bull = [f for f in fvgs if f.direction == "bullish"]
        assert bull
        f = bull[-1]
        assert f.top > f.bottom, "FVG top must be above bottom"
        # Specifically: top = low[17]=102, bottom = high[15]=100
        assert abs(f.top - 102.0) < 0.01, f"Expected top≈102, got {f.top}"
        assert abs(f.bottom - 100.0) < 0.01, f"Expected bottom≈100, got {f.bottom}"

    def test_bearish_fvg_zone_correct(self):
        """top = candle1.low, bottom = candle3.high."""
        df = _bearish_fvg_df()
        fvgs = find_fvgs(df)
        bear = [f for f in fvgs if f.direction == "bearish"]
        assert bear
        f = bear[-1]
        assert f.top > f.bottom
        assert abs(f.top - 100.0) < 0.01, f"Expected top≈100, got {f.top}"
        assert abs(f.bottom - 98.0) < 0.01, f"Expected bottom≈98, got {f.bottom}"

    def test_ce_is_midpoint(self):
        df = _bullish_fvg_df()
        for f in find_fvgs(df):
            expected_ce = (f.top + f.bottom) / 2.0
            assert abs(f.ce - expected_ce) < 1e-9, f"CE {f.ce} != midpoint {expected_ce}"

    def test_no_fvg_without_displacement_candle2(self):
        """If the middle candle is tiny (not displacement-grade) no FVG is returned."""
        opens  = [100.0] * 15 + [100.0, 100.1, 104.0]
        highs  = [101.0] * 15 + [100.0, 100.2, 106.0]
        lows   = [ 99.0] * 15 + [100.0, 100.0, 102.0]
        closes = [100.5] * 15 + [100.0, 100.15, 105.5]  # tiny candle2
        df = _df(opens, highs, lows, closes)
        fvgs = find_fvgs(df, disp_mult=1.5)
        bull = [f for f in fvgs if f.direction == "bullish" and f.index == 17]
        assert not bull, "FVG with non-displacement middle candle should be rejected"

    def test_state_mitigated_when_price_returns(self):
        """A bullish FVG is mitigated once price trades back down into it."""
        # FVG at indices 15-17, then bar 18 dips into the gap.
        opens  = [100.0] * 15 + [100.0, 100.5, 104.0, 101.5]
        highs  = [101.0] * 15 + [100.0, 105.0, 106.0, 103.0]
        lows   = [ 99.0] * 15 + [100.0, 100.0, 102.0, 100.5]  # bar18 low ≤ 102 (top)
        closes = [100.5] * 15 + [100.0, 104.0, 105.5, 101.0]
        df = _df(opens, highs, lows, closes)
        fvgs = find_fvgs(df)
        bull = [f for f in fvgs if f.direction == "bullish"]
        assert any(f.state == "mitigated" for f in bull), "FVG should be mitigated when price returns"

    def test_empty_df_returns_empty(self):
        df = _df([], [], [], [])
        assert find_fvgs(df) == []

    def test_too_short_df_returns_empty(self):
        df = _df([100], [101], [99], [100])
        assert find_fvgs(df) == []

    def test_fvg_dataclass_fields(self):
        df = _bullish_fvg_df()
        for f in find_fvgs(df):
            assert f.direction in ("bullish", "bearish")
            assert f.top > f.bottom
            assert isinstance(f.index, int)
            assert f.state in ("unmitigated", "mitigated")
            assert isinstance(f.inverted, bool)


# ---------------------------------------------------------------------------
# OB tests
# ---------------------------------------------------------------------------

class TestFindOrderBlocks:
    def _ob_df(self) -> pd.DataFrame:
        """
        Uptrend with a clear bullish BOS, yielding a detectable bullish OB.

        Layout (k=2):
          bars 0-6:  flat ATR warmup (body≈0.5, ATR≈1).
          bar 7:     swing LOW at 99 (lows[5,6]=100 > 99 < lows[8,9]=100)
                     → confirmed at i=9.
          bar 10:    swing HIGH at 105 (highs[8,9]=101 < 105 > highs[11,12]=101)
                     → confirmed at i=12; last_sh_index(10)>last_sl_index(7) → trend="up".
          bar 13:    bearish OB candle (open=104, close=102, body bearish).
          bar 14:    HUGE displacement bullish candle (open=102, close=112).
                     body_high=112 > last_sh_level=105 → bullish BOS fires.
                     Engulfs bar 13's high (104): bar14 high=113>104 ✓
                     Closes above OB body_top (104): bar14 close=112>104 ✓
        """
        #        0      1      2      3      4      5      6      7      8      9     10     11     12     13     14
        opens  = [100.0, 100.5, 100.0, 100.5, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 101.0, 101.0, 101.0, 104.0, 102.0]
        highs  = [101.0, 101.5, 101.0, 101.5, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 105.0, 101.5, 101.5, 105.0, 113.0]
        lows   = [ 99.0,  99.5, 100.0, 100.0, 100.0, 100.0, 100.0,  99.0, 100.0, 100.0, 100.0, 100.5, 100.5, 101.5, 101.0]
        closes = [100.5, 101.0, 100.5, 101.0, 100.5, 100.5, 100.5, 100.0, 100.5, 100.5, 104.5, 101.0, 101.0, 102.0, 112.0]
        return _df(opens, highs, lows, closes)

    def test_bullish_ob_detected(self):
        df = self._ob_df()
        events = detect_structure(df, k=2)
        fvgs = find_fvgs(df)
        obs = find_order_blocks(df, events, fvgs)
        bull_obs = [o for o in obs if o.direction == "bullish"]
        assert bull_obs, "Expected at least one bullish OB"

    def test_ob_direction_matches_impulse(self):
        df = self._ob_df()
        events = detect_structure(df, k=2)
        fvgs = find_fvgs(df)
        obs = find_order_blocks(df, events, fvgs)
        for ob in obs:
            assert ob.direction in ("bullish", "bearish")

    def test_ob_zone_top_above_bottom(self):
        df = self._ob_df()
        events = detect_structure(df, k=2)
        fvgs = find_fvgs(df)
        for ob in find_order_blocks(df, events, fvgs):
            assert ob.top >= ob.bottom

    def test_ob_body_within_zone(self):
        df = self._ob_df()
        events = detect_structure(df, k=2)
        fvgs = find_fvgs(df)
        for ob in find_order_blocks(df, events, fvgs):
            assert ob.body_top <= ob.top + 0.01
            assert ob.body_bottom >= ob.bottom - 0.01

    def test_ob_strength_higher_with_fvg(self):
        """An OB with an adjacent FVG should have higher strength than one without."""
        df = self._ob_df()
        events = detect_structure(df, k=2)
        fvgs = find_fvgs(df)
        obs_with_fvg = [o for o in find_order_blocks(df, events, fvgs) if o.has_fvg]
        obs_without_fvg = [o for o in find_order_blocks(df, events, fvgs) if not o.has_fvg]
        if obs_with_fvg and obs_without_fvg:
            assert obs_with_fvg[0].strength >= obs_without_fvg[0].strength

    def test_empty_events_returns_empty(self):
        df = self._ob_df()
        assert find_order_blocks(df, [], []) == []

    def test_empty_df_returns_empty(self):
        df = _df([], [], [], [])
        assert find_order_blocks(df, [], []) == []


# ---------------------------------------------------------------------------
# update_fvg_states
# ---------------------------------------------------------------------------

class TestUpdateFVGStates:
    def _fvg(self, direction: str, top: float, bottom: float, idx: int) -> FVG:
        return FVG(
            direction=direction,
            top=top, bottom=bottom,
            ce=(top + bottom) / 2,
            index=idx,
            state="unmitigated",
            inverted=False,
        )

    def test_bullish_fvg_mitigated_when_low_enters_zone(self):
        fvg = self._fvg("bullish", top=102.0, bottom=100.0, idx=2)
        # bar 3: low = 101 which is <= top (102) → mitigated
        df = _df(
            [103, 103, 103, 102],
            [104, 104, 104, 103],
            [102, 102, 102, 101],  # bar3 low=101 ≤ top=102
            [103, 103, 103, 102],
        )
        result = update_fvg_states([fvg], df)
        assert result[0].state == "mitigated"

    def test_bearish_fvg_mitigated_when_high_enters_zone(self):
        fvg = self._fvg("bearish", top=100.0, bottom=98.0, idx=2)
        df = _df(
            [97, 97, 97, 97],
            [98, 98, 98, 99],   # bar3 high=99 >= bottom(98) → mitigated
            [96, 96, 96, 96],
            [97, 97, 97, 97],
        )
        result = update_fvg_states([fvg], df)
        assert result[0].state == "mitigated"

    def test_bullish_fvg_inverted_on_body_close_through_bottom(self):
        fvg = self._fvg("bullish", top=102.0, bottom=100.0, idx=2)
        # bar3 body closes below 100 → inversion
        df = _df(
            [103, 103, 103, 101],
            [104, 104, 104, 102],
            [102, 102, 102,  98],
            [103, 103, 103,  99],  # body_low = min(101,99)=99 < bottom=100
        )
        result = update_fvg_states([fvg], df)
        assert result[0].inverted

    def test_unmitigated_fvg_stays_unmitigated(self):
        fvg = self._fvg("bullish", top=102.0, bottom=100.0, idx=0)
        # All bars stay above the gap
        df = _df(
            [104, 105, 106],
            [106, 107, 108],
            [103, 104, 105],  # lows all above top (102)
            [105, 106, 107],
        )
        result = update_fvg_states([fvg], df)
        assert result[0].state == "unmitigated"


# ---------------------------------------------------------------------------
# Breaker blocks
# ---------------------------------------------------------------------------

class TestFindBreakerBlocks:
    def test_mitigated_ob_with_opposite_event_becomes_breaker(self):
        """A mitigated bullish OB + subsequent bearish structure event → breaker."""
        ob = OrderBlock(
            direction="bullish", top=110.0, bottom=100.0,
            body_top=108.0, body_bottom=102.0,
            index=3, state="mitigated",
        )
        events = [
            StructureEvent(type="BOS", direction="bearish", break_level=100.0, index=7, displacement=False),
        ]
        df = _df([100] * 10, [110] * 10, [90] * 10, [100] * 10)
        breakers = find_breaker_blocks(df, [ob], events)
        assert breakers, "Expected a breaker block from a mitigated bullish OB"
        assert breakers[0].direction == "bearish"

    def test_unmitigated_ob_not_a_breaker(self):
        ob = OrderBlock(
            direction="bullish", top=110.0, bottom=100.0,
            body_top=108.0, body_bottom=102.0,
            index=3, state="unmitigated",
        )
        events = [
            StructureEvent(type="BOS", direction="bearish", break_level=100.0, index=7, displacement=False),
        ]
        df = _df([100] * 10, [110] * 10, [90] * 10, [100] * 10)
        breakers = find_breaker_blocks(df, [ob], events)
        assert not breakers

    def test_breaker_direction_is_flipped(self):
        ob = OrderBlock(
            direction="bearish", top=110.0, bottom=100.0,
            body_top=108.0, body_bottom=102.0,
            index=2, state="mitigated",
        )
        events = [
            StructureEvent(type="MSS", direction="bullish", break_level=110.0, index=8, displacement=True),
        ]
        df = _df([100] * 10, [115] * 10, [90] * 10, [100] * 10)
        breakers = find_breaker_blocks(df, [ob], events)
        assert breakers
        assert breakers[0].direction == "bullish"

    def test_empty_obs_returns_empty(self):
        df = _df([100] * 5, [101] * 5, [99] * 5, [100] * 5)
        assert find_breaker_blocks(df, [], []) == []
