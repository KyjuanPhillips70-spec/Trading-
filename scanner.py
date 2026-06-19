"""Per-ticker scan pipeline — §12.

scan_ticker() runs the full ICT decision tree for one symbol and returns a
Setup (or None if no trade is valid).  main.py loops the ticker list and
calls alert.py for any non-None results.  No orders are ever placed.

Pipeline steps:
  1. LOAD DATA   — daily, 4H, 1H, 15m (closed candles only).
  2. HTF BIAS    — Daily structure + EMA stack → bias.  Skip if none.
                   Indices/ETFs: require bias on BOTH 4H and 1H.
  3. DXY / SMT   — DXY inverse check; SMT divergence (confidence only).
  4. ZONE (4H)   — Nearest in-bias PD array in discount/premium.
  5. LTF TRIGGER — (a) liquidity sweep, (b) BOS/MSS, (c) OTE/OB/FVG.
                   All three required; return None if any missing.
  6. NEWS        — Blackout check.
  7. RISK        — Entry, stop, target; require R:R ≥ 1:1.
  8. CONTRACT    — 7–14 DTE, |delta| 0.45–0.65.
  9. CONFIDENCE  — Weighted score.
 10. RETURN Setup or None.
"""

from __future__ import annotations

from typing import Optional

from alert import Setup
import config


def scan_ticker(ticker: str) -> Optional[Setup]:
    """Run the full ICT pipeline for *ticker*.

    Returns a resolved Setup if all gates pass, else None.
    """
    raise NotImplementedError


def _confidence_score(
    bias_clear: bool,
    dxy_agrees: bool,
    smt_signal: Optional[str],
    ob_fvg_confluence: bool,
    clean_sweep: bool,
) -> int:
    """Compute a 0–100 confidence score from weighted boolean factors."""
    raise NotImplementedError
