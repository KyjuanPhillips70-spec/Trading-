"""DXY inverse correlation check and SMT (Smart Money Technique) divergence.

DXY inverse rule (Hard Requirement #2):
  Long equity bias → DXY should be bearish / sweeping a high and turning down.
  Short equity bias → DXY should be bullish / sweeping a low and turning up.
  Contradiction behaviour controlled by config.DXY_MODE ("block" or "warn").

SMT divergence:
  Positively correlated pairs (SPX vs QQQ, single-name vs SPX/SOXX):
    Bullish SMT: one makes a lower low, the other makes a higher low.
    Bearish SMT: one makes a higher high, the other makes a lower high.
  Negatively correlated (equities vs DXY):
    Equities make a lower low while DXY fails to make a higher high (or vice versa).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

from ict.primitives import swing_points
from ict.structure import current_trend, detect_structure


SMTSignal = Literal["bullish", "bearish", None]


@dataclass
class SMTResult:
    dxy_agrees: bool
    smt: SMTSignal
    detail: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _last_two_swings(df: pd.DataFrame, k: int) -> tuple[
    tuple[float, float] | None,   # (prev_high, last_high) or None
    tuple[float, float] | None,   # (prev_low,  last_low)  or None
]:
    """Return the last two confirmed swing highs and lows from *df*."""
    if len(df) < 2 * k + 1:
        return None, None

    sh, sl = swing_points(df, k=k)
    highs_at = [float(df["high"].iloc[i]) for i in range(len(df)) if sh.iloc[i]]
    lows_at  = [float(df["low"].iloc[i])  for i in range(len(df)) if sl.iloc[i]]

    pair_h = (highs_at[-2], highs_at[-1]) if len(highs_at) >= 2 else None
    pair_l = (lows_at[-2],  lows_at[-1])  if len(lows_at)  >= 2 else None
    return pair_h, pair_l


def _dxy_structure_bias(dxy_df: pd.DataFrame, k: int) -> Literal["long", "short", "none"]:
    """Derive DXY structural trend (HH/HL = strong dollar; LH/LL = weak dollar)."""
    if dxy_df.empty or len(dxy_df) < 2 * k + 2:
        return "none"
    events = detect_structure(dxy_df, k=k)
    trend = current_trend(events)
    if trend == "up":
        return "long"    # DXY strengthening
    if trend == "down":
        return "short"   # DXY weakening
    return "none"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_dxy(
    equity_bias: Literal["long", "short"],
    dxy_df: pd.DataFrame,
    dxy_mode: str = "block",
    swing_k: int = 3,
) -> bool:
    """Return True if DXY structure agrees with the equity bias, False if it contradicts.

    Inverse-correlation rule:
      equity long  → DXY should be bearish (weakening) → agrees.
      equity short → DXY should be bullish (strengthening) → agrees.

    If DXY structure is "none" (ranging/unclear) we treat it as non-contradicting
    and return True (the scanner will note it as unconfirmed rather than blocking).
    """
    dxy_bias = _dxy_structure_bias(dxy_df, k=swing_k)

    if dxy_bias == "none":
        return True   # no clear DXY read → don't block

    if equity_bias == "long":
        return dxy_bias == "short"   # weak DXY confirms equity longs
    else:
        return dxy_bias == "long"    # strong DXY confirms equity shorts


def smt_divergence(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    k: int = 2,
) -> SMTSignal:
    """Detect SMT divergence between two positively-correlated instruments.

    Compares the most recent pair of swing highs and lows.

    Bullish SMT: df_a makes a lower low, df_b makes a higher low
                 (or vice versa) → divergence signals manipulation/reversal up.
    Bearish SMT: df_a makes a higher high, df_b makes a lower high
                 (or vice versa) → divergence signals reversal down.
    """
    _, pair_l_a = _last_two_swings(df_a, k=k)
    _, pair_l_b = _last_two_swings(df_b, k=k)
    pair_h_a, _ = _last_two_swings(df_a, k=k)
    pair_h_b, _ = _last_two_swings(df_b, k=k)

    bullish_smt = False
    bearish_smt = False

    # Low divergence (bullish): one makes LL, other makes HL.
    if pair_l_a and pair_l_b:
        a_ll = pair_l_a[1] < pair_l_a[0]   # lower low
        b_hl = pair_l_b[1] > pair_l_b[0]   # higher low
        if (a_ll and b_hl) or (not a_ll and not b_hl and
                                pair_l_a[1] < pair_l_a[0] != (pair_l_b[1] < pair_l_b[0])):
            pass
        if (a_ll and b_hl) or (pair_l_b[1] < pair_l_b[0] and pair_l_a[1] > pair_l_a[0]):
            bullish_smt = True

    # High divergence (bearish): one makes HH, other makes LH.
    if pair_h_a and pair_h_b:
        a_hh = pair_h_a[1] > pair_h_a[0]   # higher high
        b_lh = pair_h_b[1] < pair_h_b[0]   # lower high
        if (a_hh and b_lh) or (pair_h_b[1] > pair_h_b[0] and pair_h_a[1] < pair_h_a[0]):
            bearish_smt = True

    if bullish_smt:
        return "bullish"
    if bearish_smt:
        return "bearish"
    return None


def analyze(
    equity_bias: Literal["long", "short"],
    dxy_df: pd.DataFrame,
    peer_dfs: Optional[dict[str, pd.DataFrame]] = None,
    equity_df: Optional[pd.DataFrame] = None,
    dxy_mode: str = "block",
    swing_k: int = 3,
) -> SMTResult:
    """Full DXY + SMT analysis.

    Args:
        equity_bias:  Directional bias from bias.py.
        dxy_df:       DXY OHLCV DataFrame.
        peer_dfs:     Optional dict of correlated-pair DataFrames for SMT.
        equity_df:    The equity OHLCV for peer SMT comparison.
        dxy_mode:     "block" or "warn".
        swing_k:      Swing-point strength for structure detection.

    Returns:
        SMTResult with dxy_agrees and smt signal.
    """
    dxy_agrees = check_dxy(equity_bias, dxy_df, dxy_mode=dxy_mode, swing_k=swing_k)

    detail_parts: list[str] = []
    dxy_bias = _dxy_structure_bias(dxy_df, k=swing_k)
    detail_parts.append(f"DXY structure={dxy_bias}, equity={equity_bias}, agrees={dxy_agrees}")

    # SMT divergence vs peers.
    smt_signal: SMTSignal = None
    if peer_dfs and equity_df is not None:
        for name, peer_df in peer_dfs.items():
            sig = smt_divergence(equity_df, peer_df, k=swing_k)
            if sig is not None:
                smt_signal = sig
                detail_parts.append(f"SMT vs {name}: {sig}")
                break

    # DXY inverse SMT (negatively correlated).
    if smt_signal is None and equity_df is not None and not dxy_df.empty:
        # For the inverse pair we check if one makes LL while DXY fails HH.
        _, eq_lows  = _last_two_swings(equity_df, k=swing_k)
        dxy_highs, _ = _last_two_swings(dxy_df, k=swing_k)
        if eq_lows and dxy_highs:
            eq_ll   = eq_lows[1]  < eq_lows[0]    # equity lower low
            dxy_no_hh = dxy_highs[1] < dxy_highs[0]  # DXY lower high (failed HH)
            if eq_ll and dxy_no_hh:
                smt_signal = "bullish"
                detail_parts.append("SMT (DXY inverse): equity LL + DXY failed HH → bullish SMT")
            eq_hh  = eq_lows[1] > eq_lows[0]   # reuse for high check via pair_h
            # bearish inverse: equity HH + DXY failed LL
            dxy_pair_l, _ = _last_two_swings(dxy_df, k=swing_k)
            eq_pair_h, _  = _last_two_swings(equity_df, k=swing_k)
            if dxy_pair_l and eq_pair_h:
                eq_hh2    = eq_pair_h[1] > eq_pair_h[0]
                dxy_no_ll = dxy_pair_l[1] > dxy_pair_l[0]
                if eq_hh2 and dxy_no_ll:
                    smt_signal = "bearish"
                    detail_parts.append("SMT (DXY inverse): equity HH + DXY failed LL → bearish SMT")

    if not detail_parts:
        detail_parts.append("No SMT signal detected")

    return SMTResult(
        dxy_agrees=dxy_agrees,
        smt=smt_signal,
        detail="; ".join(detail_parts),
    )
