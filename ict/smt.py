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


SMTSignal = Literal["bullish", "bearish", None]


@dataclass
class SMTResult:
    dxy_agrees: bool
    smt: SMTSignal
    detail: str


def check_dxy(
    equity_bias: Literal["long", "short"],
    dxy_df: pd.DataFrame,
    dxy_mode: str = "block",
    swing_k: int = 3,
) -> bool:
    """Return True if DXY structure agrees with the equity bias, False if it contradicts.

    Uses DXY swing structure (HH/HL vs LH/LL) as the primary signal.
    """
    raise NotImplementedError


def smt_divergence(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    k: int = 2,
) -> SMTSignal:
    """Detect SMT divergence between two positively-correlated instruments.

    Compares the most recent swing highs and lows of df_a vs df_b.
    Returns "bullish", "bearish", or None.
    """
    raise NotImplementedError


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
        equity_df:    The equity OHLCV for DXY inverse SMT check.
        dxy_mode:     "block" or "warn".
        swing_k:      Swing-point strength.

    Returns:
        SMTResult with dxy_agrees and smt signal.
    """
    raise NotImplementedError
