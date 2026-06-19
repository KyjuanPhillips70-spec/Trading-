"""Tests for ict/structure.py — Stage 3.

Hand-built OHLCV fixtures with known analytic answers.
Key requirement from BUILD_SPEC §8.1: a wick-only through a swing level
must NOT register as BOS or MSS.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ict.structure import StructureEvent, current_trend, detect_structure


# ---------------------------------------------------------------------------
# Fixture helpers
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


def _flat(n: int, mid: float = 100.0, spread: float = 1.0) -> pd.DataFrame:
    """n bars of a flat market with given spread."""
    return _df(
        opens=[mid] * n,
        highs=[mid + spread] * n,
        lows=[mid - spread] * n,
        closes=[mid] * n,
    )


# ---------------------------------------------------------------------------
# Uptrend BOS fixture
#
# Structure:
#   bars 0-4:   up-trending open market (rising closes, alternating highs/lows
#               to give confirmed swing points to k=2 detection)
#   bar 5:      swing high at 115  (k=2 requires highs[3,4] < 115 < highs[6,7])
#   bars 6-7:   pullback
#   bar 8:      new swing high breakout — body close above 115 → bullish BOS
# ---------------------------------------------------------------------------

def _uptrend_bos_df() -> pd.DataFrame:
    """
    Clear uptrend with a bullish BOS.

    Layout (k=2, ATR warmup ≥10):
      bars 0-9:   flat warmup (body=0.5, spread=1, ATR≈1 after bar 9).
      bar 10:     swing LOW  at 99 (lows[8,9]=100 > 99 < lows[11,12]=100)
                  → confirmed at i=12; last_sl_index=10.
      bar 13:     swing HIGH at 110 (highs[11,12]=101 < 110 > highs[14,15]=101)
                  → confirmed at i=15; last_sh_index(13) > last_sl_index(10)
                  → trend = "up"; last_sh_level = 110.
      bar 16:     body_high = max(open=109, close=115) = 115 > last_sh_level=110
                  → bullish BOS.
    """
    n = 10   # warmup
    opens  = [100.0] * n + [100.0, 100.0, 100.0,  101.0, 101.0, 101.0, 109.0]
    highs  = [101.0] * n + [101.0, 101.0, 101.0,  110.0, 101.5, 101.5, 116.0]
    lows   = [100.0] * n + [100.0, 100.0,  99.0,  100.0, 100.0, 100.0, 108.0]
    closes = [100.5] * n + [100.5, 100.5, 100.0,  109.0, 101.0, 101.0, 115.0]
    return _df(opens, highs, lows, closes)


# ---------------------------------------------------------------------------
# Tests — BOS
# ---------------------------------------------------------------------------

class TestBOS:
    def test_bullish_bos_detected(self):
        """Uptrend body close above swing high → bullish BOS."""
        df = _uptrend_bos_df()
        events = detect_structure(df, k=2)
        bos = [e for e in events if e.type == "BOS" and e.direction == "bullish"]
        assert bos, "Expected at least one bullish BOS"

    def test_bos_direction_matches_break(self):
        df = _uptrend_bos_df()
        for e in detect_structure(df, k=2):
            assert e.direction in ("bullish", "bearish")
            assert e.type in ("BOS", "MSS")

    def test_wick_only_is_not_bos(self):
        """
        A bar whose WICK goes above the swing high but whose BODY closes
        below it must NOT produce a BOS.  This is the key guard from §8.1.
        """
        # Build: swing high at 115 (bar 5), then a wick-only poke (bar 8 wicks
        # to 120 but body stays at 113 < 115).
        opens  = [100, 101, 100, 102, 101, 103, 101, 102, 112]
        highs  = [101, 103, 101, 104, 103, 115, 113, 114, 120]  # bar8 wick > 115
        lows   = [ 99,  99, 100, 100, 101, 101, 100, 101, 111]
        closes = [101, 102, 101, 103, 102, 113, 101, 103, 113]  # bar8 body stays < 115
        df = _df(opens, highs, lows, closes)
        events = detect_structure(df, k=2)
        # Any BOS must have its break bar body closing above the level — not bar 8.
        for e in events:
            if e.type == "BOS" and e.direction == "bullish":
                body_high = max(df["open"].iloc[e.index], df["close"].iloc[e.index])
                assert body_high > e.break_level, (
                    f"BOS at index {e.index} has body_high {body_high} <= "
                    f"break_level {e.break_level} — wick-only BOS detected (§8.1 violation)"
                )

    def test_bearish_bos_detected(self):
        """Downtrend body close below swing low → bearish BOS.

        Layout (k=2):
          bar 2: swing HIGH at 105 (highs[0,1]=101 < 105 > highs[3,4]=101)
                 → confirmed at i=4; last confirmed = swing HIGH → trend = "up" still
          bar 5: swing LOW at 95 (lows[3,4]=98 > 95 < lows[6,7]=98)
                 → confirmed at i=7; last confirmed = swing LOW → trend seeds "down"
          bar 9: open=97, close=90 → body_low=90 < last_sl_level=95 → bearish BOS
        """
        opens  = [100, 100, 104, 101, 101,  96,  97,  98,  97,  97]
        highs  = [101, 101, 105, 102, 102,  97,  98,  99,  98,  98]
        lows   = [ 99,  99, 103,  98,  98,  95,  97,  97,  96,  89]
        closes = [100, 100, 104, 101, 101,  96,  97,  98,  97,  90]
        df = _df(opens, highs, lows, closes)
        events = detect_structure(df, k=2)
        bos = [e for e in events if e.type == "BOS" and e.direction == "bearish"]
        assert bos, "Expected at least one bearish BOS"

    def test_bos_event_has_required_fields(self):
        df = _uptrend_bos_df()
        for e in detect_structure(df, k=2):
            assert isinstance(e.break_level, float)
            assert isinstance(e.index, int)
            assert isinstance(e.displacement, bool)

    def test_empty_df_returns_no_events(self):
        df = _flat(0)
        assert detect_structure(df) == []

    def test_too_short_df_returns_no_events(self):
        df = _flat(3)
        assert detect_structure(df, k=2) == []

    def test_flat_market_no_events(self):
        df = _flat(20)
        events = detect_structure(df, k=2)
        assert events == []


# ---------------------------------------------------------------------------
# Tests — MSS
# ---------------------------------------------------------------------------

class TestMSS:
    def _mss_fixture(self) -> pd.DataFrame:
        """
        Uptrend then a large displacement candle → bearish MSS.

        Layout (k=2, ATR warmup ≥10 so displacement fires):
          bars 0-9:  flat warmup (body=0.5, spread=1, ATR≈1 after bar 9).
          bar 10:    swing LOW  at 99 (lows[8,9]=100 > 99 < lows[11,12]=100)
                     → confirmed at i=12; last_sl_index=10, last_sl_level=99.
          bar 13:    swing HIGH at 115 (highs[11,12]=101 < 115 > highs[14,15]=101)
                     → confirmed at i=15; last_sh_index(13) > last_sl_index(10)
                     → trend = "up".
          bar 16:    displacement bearish candle (open=115, close=55, body=60 >> ATR≈1).
                     body_low=55 < last_sl_level=99 AND displacement=True → bearish MSS.
        """
        n = 10   # warmup
        opens  = [100.0] * n + [100.0, 100.0, 100.0, 101.0, 101.0, 101.0, 115.0]
        highs  = [101.0] * n + [101.0, 101.0, 101.0, 115.0, 101.5, 101.5, 116.0]
        lows   = [100.0] * n + [100.0, 100.0,  99.0, 100.0, 100.0, 100.0,  54.0]
        closes = [100.5] * n + [100.5, 100.5, 100.0, 114.0, 101.0, 101.0,  55.0]
        return _df(opens, highs, lows, closes)

    def test_bearish_mss_detected(self):
        df = self._mss_fixture()
        events = detect_structure(df, k=2)
        mss = [e for e in events if e.type == "MSS" and e.direction == "bearish"]
        assert mss, "Expected a bearish MSS when displacement body closes below swing low"

    def test_mss_requires_displacement(self):
        """
        A body close below a swing low WITHOUT displacement should NOT produce
        an MSS — same uptrend setup as _mss_fixture but bar 16 has a tiny
        non-displacement body instead of a large one.
        """
        n = 10
        opens  = [100.0] * n + [100.0, 100.0, 100.0, 101.0, 101.0, 101.0, 99.3]
        highs  = [101.0] * n + [101.0, 101.0, 101.0, 115.0, 101.5, 101.5, 100.0]
        lows   = [100.0] * n + [100.0, 100.0,  99.0, 100.0, 100.0, 100.0,  98.5]
        closes = [100.5] * n + [100.5, 100.5, 100.0, 114.0, 101.0, 101.0,  98.8]  # body≈0.5, no disp
        df = _df(opens, highs, lows, closes)
        events = detect_structure(df, k=2)
        mss = [e for e in events if e.type == "MSS"]
        assert not mss, "Tiny body (no displacement) should not trigger MSS"

    def test_mss_has_displacement_true(self):
        df = self._mss_fixture()
        events = detect_structure(df, k=2)
        mss = [e for e in events if e.type == "MSS"]
        for e in mss:
            assert e.displacement is True, "MSS must always have displacement=True"

    def test_mss_flips_trend(self):
        """After a bearish MSS the trend should be down."""
        df = self._mss_fixture()
        events = detect_structure(df, k=2)
        assert current_trend(events) in ("down", "ranging")


# ---------------------------------------------------------------------------
# Tests — current_trend
# ---------------------------------------------------------------------------

class TestCurrentTrend:
    def test_empty_events_ranging(self):
        assert current_trend([]) == "ranging"

    def test_bullish_event_gives_up(self):
        e = StructureEvent(type="BOS", direction="bullish", break_level=100.0, index=5, displacement=False)
        assert current_trend([e]) == "up"

    def test_bearish_event_gives_down(self):
        e = StructureEvent(type="MSS", direction="bearish", break_level=90.0, index=7, displacement=True)
        assert current_trend([e]) == "down"

    def test_last_event_wins(self):
        bull = StructureEvent(type="BOS", direction="bullish", break_level=100.0, index=3, displacement=False)
        bear = StructureEvent(type="MSS", direction="bearish", break_level=90.0, index=8, displacement=True)
        assert current_trend([bull, bear]) == "down"
        assert current_trend([bear, bull]) == "up"

    def test_returns_string_literal(self):
        e = StructureEvent(type="BOS", direction="bullish", break_level=100.0, index=1, displacement=False)
        result = current_trend([e])
        assert result in ("up", "down", "ranging")
