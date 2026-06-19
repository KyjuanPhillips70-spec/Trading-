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

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

import config
from alert import Setup
from contracts import select_contract
from data import dxy as dxy_data
from data import tradier
from ict.bias import get_bias
from ict.liquidity import detect_sweeps, find_liquidity_pools, latest_sweep
from ict.ote import compute_ote
from ict.pdarrays import find_fvgs, find_order_blocks
from ict.primitives import atr
from ict.smt import analyze as smt_analyze
from ict.structure import detect_structure
from news import is_news_blackout, next_high_impact_event
from risk import compute_risk

log = logging.getLogger(__name__)


# Peers for SMT divergence (positively correlated).
_SMT_PEERS: dict[str, list[str]] = {
    "SPX": ["QQQ"],
    "XSP": ["QQQ"],
    "QQQ": ["SPX"],
    "NVDA": ["SPX", "QQQ"],
    "PLTR": ["SPX", "QQQ"],
    "AMD": ["SPX", "QQQ"],
    "TSLA": ["SPX", "QQQ"],
}


@dataclass
class TickerData:
    """Bundle of timeframes + DXY + peers for one ticker."""
    daily: pd.DataFrame
    four_h: pd.DataFrame
    one_h: pd.DataFrame
    fifteen_m: pd.DataFrame
    dxy: pd.DataFrame
    peers: dict[str, pd.DataFrame]


# ---------------------------------------------------------------------------
# Data loading (network) — separated so the analysis core stays pure/testable.
# ---------------------------------------------------------------------------

def load_ticker_data(ticker: str) -> TickerData:
    """Pull daily + intraday from Tradier, resample to 4H/1H/15m, plus DXY."""
    daily = tradier.get_history(ticker, interval="daily")
    intraday = tradier.get_timesales(ticker, interval="15min")

    fifteen_m = intraday
    one_h = tradier.resample_ohlcv(intraday, "1H") if not intraday.empty else intraday
    four_h = tradier.resample_ohlcv(intraday, "4H") if not intraday.empty else intraday

    dxy_df, _src = dxy_data.get_dxy()

    peers: dict[str, pd.DataFrame] = {}
    for peer in _SMT_PEERS.get(ticker.upper(), []):
        try:
            peers[peer] = tradier.get_history(peer, interval="daily")
        except Exception as exc:  # pragma: no cover - network guard
            log.warning("Peer %s load failed: %s", peer, exc)

    return TickerData(daily, four_h, one_h, fifteen_m, dxy_df, peers)


# ---------------------------------------------------------------------------
# Analysis core (pure) — operates on supplied frames; no network.
# ---------------------------------------------------------------------------

def evaluate(
    ticker: str,
    data: TickerData,
    now: Optional[datetime] = None,
    today: Optional[date] = None,
) -> Optional[Setup]:
    """Run the full ICT decision tree on already-loaded *data*.

    Returns a Setup if every hard gate passes, else None.
    """
    now = now or datetime.now(timezone.utc)
    today = today or date.today()

    # --- 2. HTF BIAS ---------------------------------------------------------
    bias_res = get_bias(
        daily=data.daily, four_h=data.four_h, one_h=data.one_h,
        ticker=ticker, index_tickers=config.TICKERS_INDEX,
        ema_fast=config.EMA_FAST, ema_slow=config.EMA_SLOW,
        swing_k_htf=config.SWING_K_HTF, swing_k_ltf=config.SWING_K_LTF,
    )
    if bias_res.bias == "none":
        log.debug("%s: no HTF bias (%s)", ticker, "; ".join(bias_res.reasons))
        return None
    direction = bias_res.bias  # "long" | "short"

    # --- 3. DXY / SMT --------------------------------------------------------
    smt_res = smt_analyze(
        equity_bias=direction,
        dxy_df=data.dxy,
        peer_dfs=data.peers or None,
        equity_df=data.daily,
        dxy_mode=config.DXY_MODE,
        swing_k=config.SWING_K_HTF,
    )
    if not smt_res.dxy_agrees and config.DXY_MODE == "block":
        log.debug("%s: DXY contradicts bias (block mode)", ticker)
        return None
    if config.REQUIRE_SMT and smt_res.smt is None:
        log.debug("%s: SMT required but absent", ticker)
        return None

    # --- 5. LTF TRIGGER (1H) -------------------------------------------------
    ltf = data.one_h if not data.one_h.empty else data.fifteen_m
    if ltf.empty or len(ltf) < 2 * config.SWING_K_LTF + 2:
        return None

    # (a) liquidity sweep — long needs SSL sweep, short needs BSL sweep.
    pools = find_liquidity_pools(
        ltf, k=config.SWING_K_LTF,
        equal_tol_atr=config.EQUAL_TOL_ATR, atr_length=config.ATR_LEN,
    )
    pools = detect_sweeps(pools, ltf, sweep_window=config.SWEEP_WINDOW)
    sweep_side = "SSL" if direction == "long" else "BSL"
    sweep = latest_sweep(pools, side=sweep_side)
    if sweep is None or sweep.sweep_index is None:
        log.debug("%s: no %s sweep on LTF", ticker, sweep_side)
        return None

    # (b) structure: BOS/MSS in the bias direction at/after the sweep.
    events = detect_structure(ltf, k=config.SWING_K_LTF)
    want = "bullish" if direction == "long" else "bearish"
    structure_event = next(
        (e for e in reversed(events)
         if e.direction == want and e.index >= sweep.sweep_index),
        None,
    )
    if structure_event is None:
        log.debug("%s: no %s structure break after sweep", ticker, want)
        return None

    # (c) OTE / OB / FVG confluence.
    highs = ltf["high"].values
    lows = ltf["low"].values
    closes = ltf["close"].values
    current_price = float(closes[-1])
    sweep_extreme = float(lows[sweep.sweep_index]) if direction == "long" \
        else float(highs[sweep.sweep_index])

    if direction == "long":
        swing_origin = sweep_extreme
        swing_end = float(highs[structure_event.index])
    else:
        swing_origin = sweep_extreme
        swing_end = float(lows[structure_event.index])

    fvgs = find_fvgs(ltf, atr_length=config.DISP_ATR_LEN, disp_mult=config.DISP_MULT)
    obs = find_order_blocks(ltf, events, fvgs,
                            atr_length=config.DISP_ATR_LEN, disp_mult=config.DISP_MULT)

    ote_dir = "bullish" if direction == "long" else "bearish"
    confluence_levels = [f.ce for f in fvgs if f.direction == ote_dir]
    confluence_levels += [(o.body_top + o.body_bottom) / 2 for o in obs if o.direction == ote_dir]

    ote = compute_ote(
        swing_origin=swing_origin, swing_end=swing_end,
        current_price=current_price, direction=ote_dir,
        confluence_levels=confluence_levels or None,
        ote_low=config.OTE_LOW, ote_high=config.OTE_HIGH, ote_sweet=config.OTE_SWEET,
    )

    in_ob_fvg = bool(confluence_levels) and any(
        lo <= current_price <= hi if lo <= hi else hi <= current_price <= lo
        for lo, hi in [ote.entry_zone]
    )
    entry_type = "OTE" if ote.in_ote else ("OB" if obs else ("FVG" if fvgs else None))
    if not ote.in_ote and entry_type is None:
        log.debug("%s: price not in OTE / OB / FVG", ticker)
        return None
    if ote.invalidated:
        return None

    # --- 6. NEWS -------------------------------------------------------------
    blocked, event = is_news_blackout(
        now, before_h=config.NEWS_BEFORE_H, after_h=config.NEWS_AFTER_H,
    )
    if blocked:
        log.debug("%s: news blackout (%s)", ticker, event.title if event else "?")
        return None
    next_event = next_high_impact_event(now)

    # --- 7. RISK -------------------------------------------------------------
    entry = current_price
    ob_far_edge = sweep_extreme
    if obs:
        ob = obs[-1]
        ob_far_edge = ob.bottom if direction == "long" else ob.top

    # Nearest unswept pool in the trade direction for the target.
    target_side = "BSL" if direction == "long" else "SSL"
    pool_targets = [
        p.pool_level for p in pools
        if p.side == target_side and not p.swept
        and (p.pool_level > entry if direction == "long" else p.pool_level < entry)
    ]
    next_pool = (min(pool_targets) if direction == "long" else max(pool_targets)) \
        if pool_targets else None

    atr_series = atr(ltf, length=config.ATR_LEN)
    atr_val = float(atr_series.iloc[-1]) if not atr_series.dropna().empty else 0.0

    risk_res = compute_risk(
        entry=entry, sweep_extreme=sweep_extreme, ob_far_edge=ob_far_edge,
        next_liquidity_pool=next_pool, direction=direction, atr_value=atr_val,
        stop_buffer_atr=config.STOP_BUFFER_ATR, min_rr=config.MIN_RR,
    )
    if risk_res is None:
        log.debug("%s: R:R below %.1f", ticker, config.MIN_RR)
        return None

    # --- 8. CONTRACT ---------------------------------------------------------
    contract = select_contract(
        ticker=ticker, direction=direction,
        entry_price=risk_res.entry, stop_price=risk_res.stop,
        target_price=risk_res.target, today=today,
        dte_min=config.DTE_MIN, dte_max=config.DTE_MAX,
        delta_min=config.DELTA_MIN, delta_max=config.DELTA_MAX,
    )
    if contract is None:
        log.debug("%s: no suitable contract", ticker)
        return None

    # --- 9. CONFIDENCE -------------------------------------------------------
    confidence = _confidence_score(
        bias_clear=True,
        dxy_agrees=smt_res.dxy_agrees,
        smt_signal=smt_res.smt,
        ob_fvg_confluence=in_ob_fvg or bool(ote.has_confluence),
        clean_sweep=True,
    )

    # --- 10. RETURN ----------------------------------------------------------
    return Setup(
        ticker=ticker,
        direction=direction.upper(),
        confidence=confidence,
        daily_bias=bias_res.daily_bias,
        four_h_bias=bias_res.four_h_bias,
        one_h_bias=bias_res.one_h_bias,
        ema_stack_ok=bias_res.ema_stack_ok,
        dxy_agrees=smt_res.dxy_agrees,
        smt_signal=smt_res.smt,
        sweep_side=sweep_side,
        sweep_level=sweep.pool_level,
        structure_event=structure_event.type,
        entry_type=entry_type or "OTE",
        entry=risk_res.entry,
        stop=risk_res.stop,
        target=risk_res.target,
        rr=risk_res.rr,
        contract=contract,
        news_clear=not blocked,
        next_news_event=next_event,
    )


def scan_ticker(ticker: str) -> Optional[Setup]:
    """Load data and run the full ICT pipeline for *ticker*.

    Returns a resolved Setup if all gates pass, else None.
    """
    data = load_ticker_data(ticker)
    return evaluate(ticker, data)


def _confidence_score(
    bias_clear: bool,
    dxy_agrees: bool,
    smt_signal: Optional[str],
    ob_fvg_confluence: bool,
    clean_sweep: bool,
) -> int:
    """Compute a 0–100 confidence score from weighted boolean factors.

    Weights (sum to 100):
        bias clarity        35
        clean sweep         25
        OB + FVG confluence 20
        DXY agreement       10
        SMT divergence      10
    """
    score = 0
    if bias_clear:
        score += 35
    if clean_sweep:
        score += 25
    if ob_fvg_confluence:
        score += 20
    if dxy_agrees:
        score += 10
    if smt_signal is not None:
        score += 10
    return score
