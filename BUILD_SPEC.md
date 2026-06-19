# BUILD_SPEC.md — ICT Swing-Options ALERT System

> **For the coding agent (Claude Code on the web).** This is the authoritative build spec. Implement it in the staged order in §14. Build one stage, open a PR, stop, and wait for review before the next stage. Do not auto-execute trades anywhere. This system only *alerts*; a human places every trade.

-----

## 1. What we are building

A Python service that scans a fixed list of tickers, applies ICT (Inner Circle Trader) swing logic across multiple timeframes, and sends a Telegram alert when a high-probability **swing options** setup appears. It runs unattended on a GitHub Actions cron schedule. The output of every alert is: direction, the reasoning, an entry level, a stop, a target at **1:1 risk/reward**, and a **suggested option contract** (≥ 7 days to expiry, favorable Greeks).

**Tickers (two groups):**

- Index / broad-market (cash-settled where noted): `SPX`, `XSP`, `QQQ`
- Blue-chip tech & momentum (single-name equity options): `NVDA`, `PLTR`, `AMD`, `TSLA`

**Hard requirements (these are gates, not preferences — never emit an alert that violates them):**

1. For indices/ETFs there must be a **clear directional bias on BOTH the 4H and 1H timeframes** before a trade is considered.
1. Directional bias must be **cross-checked against the US Dollar Index (DXY)** using the inverse-correlation rule (DXY up ⇒ equities pressured down, and vice versa).
1. Entry must be confirmed on a **lower timeframe** using ICT concepts: a **liquidity sweep** + a **break/shift of structure (BOS or MSS)** + a **PD-array entry** (Fair Value Gap / Order Block / OTE).
1. Risk/reward must be **≥ 1:1**.
1. The suggested contract must have **≥ 7 calendar days to expiration** (target 7–14 DTE) with **favorable Greeks** (see §10).
1. **No alert** if a high-impact USD news event falls inside the configured blackout window (see §9).

-----

## 2. Tech stack

- **Language:** Python 3.11+
- **Libraries:** `requests`, `pandas`, `numpy`, `yfinance`, `python-dateutil`, `pytz`, `tenacity` (retries). Optional `pandas-ta` (or compute EMA/ATR inline — inline preferred to avoid a heavy dependency).
- **Data — price/OHLCV + options + Greeks:** **Tradier** REST (sandbox). Tradier returns option Greeks inline (delta/gamma/theta/vega/IV).
- **Data — DXY:** `yfinance` ticker `DX-Y.NYB`. Fallback proxy: `UUP` via Tradier (or `DX=F` via yfinance) if `DX-Y.NYB` fails.
- **News:** ForexFactory weekly XML feed (cached once per week).
- **Alerts:** Telegram Bot API (`sendMessage`).
- **Hosting/schedule:** GitHub Actions cron.

-----

## 3. Repository structure

```
ict-swing-alerts/
├── README.md
├── requirements.txt
├── .gitignore                 # must ignore .env, __pycache__, *.cache, data/
├── config.py                  # all tunable parameters (see §13)
├── .github/
│   └── workflows/
│       └── scan.yml           # cron schedule (see §11)
├── data/
│   ├── tradier.py             # Tradier REST client (price + options)
│   ├── dxy.py                 # DXY via yfinance, with UUP fallback
│   └── cache.py               # simple on-disk JSON cache (news, expirations)
├── ict/
│   ├── primitives.py          # swing points, ATR, displacement, premium/discount
│   ├── structure.py           # BOS, MSS/CHoCH
│   ├── liquidity.py           # BSL/SSL pools, equal highs/lows, sweeps
│   ├── pdarrays.py            # FVG, order blocks, breaker blocks
│   ├── ote.py                 # Fibonacci OTE zone + projections
│   ├── bias.py                # HTF bias (structure + EMA stack), multi-timeframe
│   └── smt.py                 # DXY inverse check + SMT divergence
├── news.py                    # ForexFactory parse + blackout filter
├── contracts.py               # option selection (DTE, delta, settlement labels)
├── risk.py                    # stop/target, 1:1 sizing, underlying→option P/L via delta
├── alert.py                   # Telegram sender + message formatting
├── scanner.py                 # per-ticker pipeline (the §8 logic)
├── main.py                    # entrypoint: loop tickers, call scanner, send alerts
└── tests/
    ├── fixtures/              # small CSVs of OHLCV with known patterns
    ├── test_primitives.py
    ├── test_structure.py
    ├── test_liquidity.py
    ├── test_pdarrays.py
    ├── test_ote.py
    └── test_pipeline.py
```

-----

## 4. Configuration & secrets

Read all secrets from environment variables. **Never hard-code keys; never commit them.** In production they come from GitHub Actions secrets; for local/manual runs they come from a `.env` (git-ignored).

Required env vars:

- `TRADIER_TOKEN` — Tradier sandbox access token
- `TRADIER_BASE_URL` — default `https://sandbox.tradier.com/v1`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

`config.py` holds all non-secret tunables (thresholds, ticker list, timeframes, blackout windows) as named constants with sensible defaults from §13.

-----

## 5. Data layer

### 5.1 `data/tradier.py`

A thin client. Auth header on every request: `Authorization: Bearer {TRADIER_TOKEN}`, `Accept: application/json`. Wrap calls with `tenacity` retry (exponential backoff, max 4 attempts) and respect a self-imposed rate limit of **≤ 120 requests/minute**. Batch quote requests accept **up to 100 symbols** per call — use this.

Implement:

- `get_history(symbol, interval="daily", start, end)` → `GET /markets/history` → return a `pandas.DataFrame` indexed by date with columns `open, high, low, close, volume`.
- `get_timesales(symbol, interval, start, end, session_filter="open")` → `GET /markets/timesales` for intraday bars. `interval` ∈ {`1min`,`5min`,`15min`}. Resample to 1H and 4H in pandas from 15min/5min bars (Tradier intraday max granularity is minute-based; build 1H/4H by resampling).
- `get_quotes(symbols: list[str])` → `GET /markets/quotes?symbols=a,b,c` (≤100).
- `get_option_expirations(symbol)` → `GET /markets/options/expirations?symbol=...&includeAllRoots=true&strikes=true`.
- `get_option_chain(symbol, expiration)` → `GET /markets/options/chains?symbol=...&expiration=YYYY-MM-DD&greeks=true` → return per-strike rows including `strike, option_type, bid, ask, last, volume, open_interest, greeks{delta,gamma,theta,vega,bid_iv,mid_iv,ask_iv}`.
- `get_option_roots(symbol)` → `GET /markets/options/lookup?underlying=...` (for weekly roots like `SPXW`).

> Note: sandbox quotes are ~15 min delayed. Acceptable for swing. Build all higher timeframes (1H, 4H) by **resampling** the finest intraday series; always work on **closed candles only** (drop the still-forming last bar).

### 5.2 `data/dxy.py`

- `get_dxy(period="3mo", interval="1d")` → `yfinance.Ticker("DX-Y.NYB").history(...)` → standardized OHLCV DataFrame.
- On failure (empty frame or rate-limit error), fall back to `UUP` via Tradier daily history, and flag `source="UUP_proxy"` so the alert can note it.
- Provide a 4H DXY series by pulling `interval="1h"` from yfinance where available and resampling; if intraday DXY is unavailable, use daily DXY structure only and note the limitation.

### 5.3 `data/cache.py`

A trivial JSON on-disk cache with TTL. Used for the ForexFactory weekly file (TTL 6 days) and option expirations (TTL 1 day). Key by string; store `{"ts":..., "data":...}`.

-----

## 6. Core primitives — `ict/primitives.py`

These are the building blocks everything else depends on. Implement and unit-test these FIRST.

- **`atr(df, length=14)`** → standard Average True Range series.
- **`swing_points(df, k=2)`** → returns two boolean Series (`swing_high`, `swing_low`). A bar at index *i* is a **swing high** if its `high` is strictly greater than the `high` of the `k` bars immediately before AND the `k` bars immediately after it. Swing low is the mirror with `low`. Use `k=2` for execution timeframes (1H/15m) and `k=3` for HTF (4H/Daily); expose `k` as a parameter.
- **`displacement(df, atr_length=10, mult=1.5)`** → boolean Series. A candle is **displacement** if `abs(close-open) >= mult * atr(df, atr_length).shift(1)` **OR** the candle is the middle candle of a valid FVG (see §7.1). Displacement is what separates a real structural break from a stop-run wick.
- **`dealing_range(df, lookback)`** → returns the most recent confirmed swing low and swing high defining the active range, plus helper levels: `equilibrium = (hi+lo)/2`, with anything above EQ = **premium** and below EQ = **discount**.
- **`ema(series, length)`** → exponential moving average.

**Acceptance:** unit tests in `tests/test_primitives.py` confirm swing detection, ATR, and displacement against hand-built fixtures with known answers.

-----

## 7. PD arrays — `ict/pdarrays.py`

### 7.1 Fair Value Gap (FVG / imbalance) — exact 3-candle definition

Index the current candle as candle 3 (so candle 1 is `shift(2)`):

- **Bullish FVG (BISI):** `low[3] > high[1]`. The gap zone is `[high[1], low[3]]`.
- **Bearish FVG (SIBI):** `high[3] < low[1]`. The gap zone is `[high[3], low[1]]`.
- **Consequent Encroachment (CE):** midpoint of the gap = `(top+bottom)/2` — the ideal fill/entry level.
- **Validity filter:** require candle 2 (the middle candle) to be displacement-grade (body ≥ `mult*ATR`); discard micro-gaps.
- Track each FVG’s state: `unmitigated` until price trades back through it, then `mitigated`.
- **Inversion FVG (IFVG):** a FVG that price closes a *body* through against its direction flips polarity (a failed bullish FVG becomes bearish support→resistance). Implement as an optional flag.

Return a list of `FVG{direction, top, bottom, ce, index, state}`.

### 7.2 Order Blocks

- **Bullish OB:** the **last down-close (bearish) candle before** an up-move that breaks structure. Zone = that candle’s `[low, high]` (also store body `[open, close]`).
- **Bearish OB:** the last up-close candle before a down-move that breaks structure.
- **Validity (require all four):** (a) the impulse leg engulfs/takes the OB candle’s opposite extreme, (b) price closes beyond the OB body, (c) the move leaves an **FVG** on the same/next lower timeframe, (d) the move produces a **structure shift (MSS)** — see §8. An OB with an adjacent FVG is materially stronger; expose a `strength` score.
- Return `OrderBlock{direction, top, bottom, body_top, body_bottom, index, has_fvg, strength, state}`.

### 7.3 Breaker Block

A failed OB: price sweeps liquidity, fails the OB, closes through it, and shifts structure; the broken OB then acts from the opposite side. Implement as `breaker_blocks(df)` returning the flipped zones.

**Acceptance:** `tests/test_pdarrays.py` proves bullish/bearish FVG detection (`low>high[2]` / `high<low[2]`), CE math, and OB detection on fixtures.

-----

## 8. Structure & liquidity

### 8.1 `ict/structure.py`

Maintain the running sequence of confirmed swing highs/lows (from §6) to classify trend (higher-highs/higher-lows = up; lower-highs/lower-lows = down).

- **Break of Structure (BOS) — continuation.** Bullish BOS = a candle **body close above** the most recent confirmed swing high while in an uptrend. Bearish BOS = body close below the most recent swing low in a downtrend. **Require a body close, not a wick.**
- **Market Structure Shift (MSS) / CHoCH — reversal.** In a downtrend, a **body close above the most recent lower-high accompanied by displacement** = bullish MSS. In an uptrend, a body close below the most recent higher-low with displacement = bearish MSS. (Treat MSS and CHoCH as synonyms; MSS = the *displacement-confirmed* version, which is what we require for entries.)

Return structured events: `{type: "BOS"|"MSS", direction, break_level, index, displacement: bool}`.

### 8.2 `ict/liquidity.py`

- **Buy-side liquidity (BSL):** resting stops **above** old/equal highs, prior-day high (PDH), prior-week high (PWH). **Sell-side liquidity (SSL):** below old/equal lows, PDL, PWL.
- **Equal highs/lows:** two or more swing highs (or lows) within tolerance `equal_tol` (default `0.1 * ATR` of the timeframe, or 0.05–0.10% of price — configurable). Flag as an engineered liquidity pool.
- **Liquidity sweep / raid / stop hunt:** price **wicks beyond** a known pool then **closes back through** the level within `sweep_window` candles (default 3). Detection for a BSL sweep: `high > pool_level` AND `close < pool_level` within the window (a swept high that closes back below → bearish-context sweep). Mirror for SSL. **The reversal close — not the poke — defines the sweep.**
- Encode the directional rule: in a **bullish** HTF bias, look for a **sweep of SSL** (below an old low) before continuation up; in a **bearish** bias, a **sweep of BSL** before continuation down.

Return `{pool_level, side: "BSL"|"SSL", swept: bool, sweep_index, source: "equal_highs"|"PDH"|...}`.

**Acceptance:** `tests/test_liquidity.py` and `tests/test_structure.py` validate sweep detection and BOS/MSS on fixtures, including a wick-only case that must NOT register as a BOS.

-----

## 9. OTE & news

### 9.1 `ict/ote.py`

Anchor the Fibonacci on the **impulse/displacement leg** (bullish: swing low → swing high; bearish: swing high → swing low). Use body-to-body anchors for stability.

- **OTE zone = 62%–79% retracement.** `0.705` is the central sweet spot; `0.5` = equilibrium.
- A retracement entry qualifies only if price is inside 62–79% **and** there is confluence (an FVG, OB, or equal-liquidity level) inside that zone.
- **Profit projections** (standard deviations ICT uses): `-0.27, -0.62, -1.0, -2.0, -2.5, -4.0` measured from the leg.
- **Invalidation:** a candle **body** close beyond the `1.0` level (the swing origin / sweep extreme). Wicks through `1.0` do not invalidate.

Return `{in_ote: bool, level: float, entry_zone: (lo,hi), stop_ref: float, projections: {...}}`.

### 9.2 `news.py` (ForexFactory)

- Download `https://nfs.faireconomy.media/ff_calendar_thisweek.xml` (fallback `.json`). **Cache once per week** — FF throttles downloads (≈2 per 5 min). Use `data/cache.py` with a 6-day TTL.
- Parse events: `title, country, date/time, impact`.
- **Filter to `country == "USD"` and `impact == "High"`.**
- **Blackout rule:** suppress new-entry alerts within the window `news_before_h` before through `news_after_h` after any High-impact USD event. Defaults: 24h before, 2h after (configurable). When inside the window, the scanner returns `news_block=True` and the reason.
- Provide `next_high_impact_event()` so alerts can show the next event even when not blocking.

-----

## 10. Bias, SMT, contracts, risk

### 10.1 `ict/bias.py` — HTF directional bias (multi-timeframe)

Top-down: **Daily → 4H → 1H/15m.**

- **Daily bias:** combine (a) market structure (HH/HL = bullish, LH/LL = bearish) with (b) the **10/20 EMA stack** — bullish when EMA10 > EMA20, both rising, gap widening (“stacking”); bearish is the mirror. Bias is **clear** only when structure and EMA agree; otherwise `bias = "none"` and the ticker is skipped.
- **4H:** locate the nearest in-bias PD array (for longs: a bullish OB or bullish FVG sitting in discount).
- **1H / 15m:** provide the entry trigger series for §8 (sweep + MSS + OTE/OB/FVG).
- **For indices/ETFs (`SPX`,`XSP`,`QQQ`): require a clear bias on BOTH 4H and 1H** (Hard Requirement #1). For single names, require Daily + 4H agreement and a 1H trigger.

Return `{bias: "long"|"short"|"none", htf_zone, reasons: [...]}`.

### 10.2 `ict/smt.py` — DXY inverse + SMT divergence

- **DXY inverse check (Hard Requirement #2):** read DXY structure. If equities bias is **long**, DXY should be bearish/sweeping a high and turning down (confirms long). If DXY structure strongly *contradicts* the equity bias, **downgrade or skip** (configurable `dxy_mode`: `block` or `warn`).
- **SMT divergence:** compare two correlated instruments at a matching swing.
  - Positively correlated (e.g., **SPX vs QQQ**, or a single name vs `SPX`/`SOXX`): bullish SMT = one makes a *lower low* while the other makes a *higher low*; bearish SMT = one makes a *higher high* while the other makes a *lower high*.
  - Negatively correlated (equities vs **DXY**): at a turn, equities make a lower low while DXY fails to make a higher high (or vice versa) → divergence flags manipulation/reversal.
- Output `{dxy_agrees: bool, smt: "bullish"|"bearish"|None, detail}`. `require_smt` config flag decides whether SMT is mandatory (default: **not** mandatory but adds to confidence score).

### 10.3 `contracts.py` — option selection

Given ticker, direction, and the underlying entry/stop/target:

1. Pull expirations (`get_option_expirations`); choose the nearest expiry with **DTE between 7 and 14** (Hard Requirement #5). If none in range, pick the smallest DTE ≥ 7 and note it.
1. Pull the chain with Greeks. Select **calls for long, puts for short**.
1. **Strike/Greeks targeting:** choose a contract with **|delta| ≈ 0.45–0.65** (ATM to slightly ITM) — good directional expectancy with manageable theta. Reject |delta| < 0.30 (lottery tickets) for a 1:1 R:R. Among candidates, prefer tighter bid/ask spread and adequate open interest/volume (liquidity).
1. **Flag Greeks:** report `delta, theta (as % of premium/day), gamma, vega, IV`. Warn if IV is elevated relative to recent (avoid buying rich premium into a known event).
1. **Settlement labels (must be shown in the alert):**
- `SPX`, `XSP` → **cash-settled, European-style, Section 1256 (60/40 tax), no early assignment.** (`XSP` ≈ 1/10 SPX notional — good for smaller accounts; watch wider spreads.) Use weekly roots (`SPXW`/`XSPW`) for PM-settled weeklies via `includeAllRoots`.
- `QQQ`, `NVDA`, `PLTR`, `AMD`, `TSLA` → **American-style, physically settled (shares), standard equity tax, early-assignment/pin risk.**

Return a `Contract{symbol(OCC), type, strike, expiry, dte, bid, ask, mid, delta, theta, gamma, vega, iv, oi, volume, settlement_note}`.

### 10.4 `risk.py` — 1:1 risk/reward

- **Stop (underlying):** just beyond the sweep extreme / far edge of the OB (+ buffer = `stop_buffer_atr * ATR`, default 0.1).
- **Target (underlying):** the next liquidity pool (old high/low or equal H/L) in the bias direction **OR** a 1:1 distance from entry, whichever yields **R:R ≥ 1:1** (Hard Requirement #4). If the nearest liquidity target gives < 1:1, fall back to exactly 1:1.
- **Translate to the option:** estimate option P/L at target and stop using `delta` (and `gamma` for the larger move) so the alert shows approximate contract gain/loss. This is an estimate, clearly labeled.

-----

## 11. GitHub Actions schedule — `.github/workflows/scan.yml`

- Trigger: `schedule` cron + `workflow_dispatch` (so it can be run manually from the phone).
- Run every 15–30 minutes during US market hours. **Cron is in UTC and is imprecise (can lag a few minutes) — fine for swing.** Example: every 20 min, 13:30–20:10 UTC, Mon–Fri (covers 09:30–16:00 ET during DST; widen for standard time).
- Steps: checkout → setup Python 3.11 → `pip install -r requirements.txt` → `python main.py` with secrets injected as env.
- Pull `TRADIER_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` from `secrets`.
- Keep runs short (the free tier gives limited monthly minutes for private repos; a public repo gets unlimited Actions minutes). Cache pip to speed runs.

Skeleton:

```yaml
name: ict-scan
on:
  workflow_dispatch:
  schedule:
    - cron: "*/20 13-20 * * 1-5"
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: "pip" }
      - run: pip install -r requirements.txt
      - run: python main.py
        env:
          TRADIER_TOKEN: ${{ secrets.TRADIER_TOKEN }}
          TRADIER_BASE_URL: https://sandbox.tradier.com/v1
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

> **Sandbox note for Claude Code on the web:** the build sandbox blocks `.env`/local secrets and restricts network by default. Allow `pypi.org`/`files.pythonhosted.org` so `pip install` works, and allow the data domains (`sandbox.tradier.com`, `nfs.faireconomy.media`, `query1.finance.yahoo.com`, `api.telegram.org`) when running tests. Real scheduled runs happen in **GitHub Actions**, not the build sandbox, using the repo secrets above.

-----

## 12. The pipeline — `scanner.py` (per ticker)

```
scan_ticker(ticker):
  1. LOAD DATA: daily, 4H, 1H, 15m (resampled from Tradier intraday). Use closed candles only.
  2. HTF BIAS (bias.py):
       - Daily structure + 10/20 EMA stack -> bias in {long, short, none}. If none -> RETURN no-trade.
       - Indices/ETFs: require clear bias on BOTH 4H and 1H. Else RETURN no-trade.
  3. DXY / SMT (smt.py):
       - DXY inverse check. If contradicts and dxy_mode=block -> RETURN no-trade (else add warning).
       - Compute SMT divergence; add to confidence.
  4. ZONE (4H): nearest in-bias PD array (bullish OB/FVG in discount for longs; mirror for shorts).
  5. LTF TRIGGER (1H/15m), ALL required:
       a. liquidity sweep of SSL (long) / BSL (short)  [liquidity.py]
       b. BOS or MSS (displacement-confirmed) in bias direction  [structure.py]
       c. price in OTE 62-79% AND/OR tapping the OB/FVG (CE)  [ote.py / pdarrays.py]
       - If any missing -> RETURN no-trade.
  6. NEWS (news.py): if news_block -> RETURN no-trade (note the event).
  7. RISK (risk.py): compute entry, stop (beyond sweep/OB), target (next pool or 1:1). Require R:R >= 1:1.
  8. CONTRACT (contracts.py): choose 7-14 DTE, |delta| 0.45-0.65, liquid, with Greeks + settlement note.
  9. CONFIDENCE SCORE: sum weighted factors (bias clarity, DXY agree, SMT, OB+FVG confluence, clean sweep).
 10. RETURN Setup{...} or None.
```

`main.py` loops the ticker list, collects non-None setups, and calls `alert.py`. Never place an order.

-----

## 13. Parameters (`config.py` defaults)

|Parameter                           |Default                       |Meaning                             |
|------------------------------------|------------------------------|------------------------------------|
|`TICKERS_INDEX`                     |`["SPX","XSP","QQQ"]`         |require 4H+1H bias                  |
|`TICKERS_SINGLE`                    |`["NVDA","PLTR","AMD","TSLA"]`|require Daily+4H bias               |
|`SWING_K_LTF` / `SWING_K_HTF`       |`2` / `3`                     |fractal strength                    |
|`ATR_LEN`                           |`14`                          |ATR length                          |
|`DISP_ATR_LEN` / `DISP_MULT`        |`10` / `1.5`                  |displacement threshold              |
|`EMA_FAST` / `EMA_SLOW`             |`10` / `20`                   |daily bias EMAs                     |
|`EQUAL_TOL_ATR`                     |`0.1`                         |equal-high/low tolerance            |
|`SWEEP_WINDOW`                      |`3`                           |candles to close back through a pool|
|`OTE_LOW` / `OTE_HIGH` / `OTE_SWEET`|`0.62` / `0.79` / `0.705`     |OTE zone                            |
|`STOP_BUFFER_ATR`                   |`0.1`                         |stop padding                        |
|`MIN_RR`                            |`1.0`                         |minimum risk/reward                 |
|`DTE_MIN` / `DTE_MAX`               |`7` / `14`                    |contract expiry window              |
|`DELTA_MIN` / `DELTA_MAX`           |`0.45` / `0.65`               |target                              |
|`NEWS_BEFORE_H` / `NEWS_AFTER_H`    |`24` / `2`                    |blackout window                     |
|`DXY_MODE`                          |`"block"`                     |`block` or `warn`                   |
|`REQUIRE_SMT`                       |`False`                       |mandatory SMT?                      |

-----

## 14. Build order (STAGED — one PR per stage, stop after each)

1. **Stage 0 — scaffold.** Repo structure, `requirements.txt`, `config.py`, `.gitignore`, empty modules with type hints + docstrings. README with run instructions. *No logic yet.*
1. **Stage 1 — data layer.** `data/tradier.py`, `data/dxy.py`, `data/cache.py`. Add a `scripts/smoke_data.py` that pulls one ticker’s daily + 15m and prints shapes. Test against sandbox.
1. **Stage 2 — primitives + tests.** `ict/primitives.py` with full `tests/test_primitives.py`. Must pass before proceeding.
1. **Stage 3 — PD arrays + structure + liquidity + tests.** `pdarrays.py`, `structure.py`, `liquidity.py` and their tests (`test_pdarrays.py`, `test_structure.py`, `test_liquidity.py`), incl. the wick-only non-BOS case.
1. **Stage 4 — OTE + bias + SMT.** `ote.py`, `bias.py`, `smt.py` with `test_ote.py`.
1. **Stage 5 — news + risk + contracts.** `news.py` (with caching), `risk.py`, `contracts.py`.
1. **Stage 6 — pipeline + alerts.** `scanner.py`, `main.py`, `alert.py`, `tests/test_pipeline.py` (end-to-end on fixtures). Send a real test alert to Telegram.
1. **Stage 7 — schedule.** `.github/workflows/scan.yml`, run via `workflow_dispatch`, verify a clean cloud run.

Each stage: write code → write/run tests → open PR → **stop and wait**.

-----

## 15. Alert format (Telegram, Markdown)

Each alert must contain, clearly labeled:

```
🔔 ICT SWING SETUP — {TICKER} {LONG/SHORT}  (confidence {n}/100)

Bias: Daily {dir} (EMA stack {ok}); 4H {dir}; 1H {dir}
DXY: {agrees/contradicts}  |  SMT: {bullish/bearish/none}
Trigger: swept {SSL/BSL} @ {level} → {BOS/MSS} → entry in {OTE/OB/FVG}

Entry:  {price}
Stop:   {price}   ({risk} away)
Target: {price}   (R:R {x.x} : 1)

Contract: {OCC symbol}
  {type} {strike} exp {date} ({dte} DTE)
  Δ {delta}  Θ {theta}/day  Γ {gamma}  V {vega}  IV {iv}
  Est. debit ~{mid}  | est. P/L at target ~{+}, at stop ~{-}
  {settlement note}

News: {clear / next high-impact USD event @ time}
⚠️ Alert only — not financial advice. Verify before trading.
```

-----

## 16. Caveats to encode (print in README)

- ICT is discretionary and partly subjective (swing detection, “displacement,” bias thresholds). This system mechanizes a reasonable interpretation; it is **decision support, not a proven edge**. Backtest before risking capital.
- Tradier sandbox data is ~15 min delayed (fine for swing, not scalping). `yfinance` DXY is unofficial and can rate-limit (429) — fall back to UUP. ForexFactory throttles downloads — cache weekly.
- Greeks from Tradier are reference values; treat estimated option P/L as approximate.
- Settlement/tax notes are general, not tax advice. Options carry substantial risk; a 1:1 R:R on long premium still loses to theta if the move stalls.
- Keep a human in the loop: every alert is a candidate, not an instruction.
