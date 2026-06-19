# Research Dossier & Coding-Agent Prompt Material: An ICT-Based Swing-Options ALERT System

## TL;DR

- This dossier gives you (1) codifiable, rule-by-rule definitions of every ICT concept you listed, (2) a concrete free/low-cost Python tech stack — Tradier (price + options Greeks), yfinance (DXY), the ForexFactory XML feed (news), and Telegram/Discord for alerts — and (3) a ready-to-hand coding-agent prompt that fuses HTF bias → DXY/SMT cross-check → LTF liquidity-sweep + FVG/OTE/order-block entry → 1:1 contract selection → news filter.
- The single best build: **Python 3.11+, Tradier Sandbox (free) for OHLCV + options chains with ORATS-supplied Greeks, yfinance for DXY (`DX-Y.NYB`)/proxy, ForexFactory `nfs.faireconomy.media` weekly XML for news, run on a GitHub Actions cron or a $5 VPS, alert via Telegram bot.** Tradier is the linchpin because it is the only free source that returns delta/theta/gamma/vega inline with the chain.
- Treat this as an ALERT/decision-support system, not auto-execution. ICT is discretionary and partly subjective (swing-point detection, “displacement,” bias) — the system should surface high-probability setups with full reasoning and let you pull the trigger.

## Key Findings

### A. ICT methodology is codifiable but rests on a few subjective primitives

Every ICT concept reduces to operations on swing highs/lows, candle bodies/wicks, and time windows. The two primitives you must define once and reuse everywhere are: (1) a **fractal swing point** (a high with N lower highs on each side, typically N=2 or 3), and (2) **displacement** (a candle or leg whose range materially exceeds recent average range — operationalize as body ≥ 1.5× the ATR of the prior 10–20 candles, and/or a leg that leaves an FVG). Get those two right and BOS, MSS/CHoCH, liquidity sweeps, order blocks, FVGs and OTE all become deterministic.

### B. The “swing” application is daily-bias + lower-timeframe entry

The specific video you cited — **“ICT Forex – Secrets To Swing Trading” (Inner Circle Trader, published Dec 18, 2017, 27:30, part of the ICT Market Maker Primer Course)** — teaches a comparatively simple, mechanical swing model that pre-dates the “draw on liquidity” vocabulary:

- **Bias timeframe = the DAILY chart**, because (ICT’s words, per the lecture-note transcription) “the daily chart really is the most widely followed chart in the banking sector.” 
- **Bias tool = 10 & 20 EMA “stacking”** on the daily: bullish when the 10 EMA is above the 20 EMA, both rising, and the gap between them is widening (“stacking”);  bearish is the mirror.
- **Execution/swing timeframe = the HOURLY (H1)**: “hourly chart to me is a real good swing trading time frame.”  Once the daily is trending, drop to H1 and take an **OTE (Optimal Trade Entry)** on the retracement, tolerating a dip below the H1 20-EMA “as long as the 10 EMA has not crossed below the 20.” 
- **Selectivity**: “You just need to know the few times a month or couple times a week when it’s really loaded into one direction.”  Market = Trending vs. Consolidation; only trade with HTF momentum.
- His broader/later swing teaching (2022 mentorship and after) layers on: weekly→daily→4H/1H top-down, buy-side/sell-side liquidity pools as targets (“draw on liquidity”), and PD-array entries (OTE/OB/FVG). The 2017 video itself does **not** use weekly bias, “draw on liquidity,” or explicit multi-day hold rules — those are later-era additions. Build the system to use **Daily (and optionally Weekly) for bias, 4H for the zone, and 1H/15m for the entry trigger**, which reconciles the 2017 video with his later swing framework.

### C. The cheapest accurate stack hinges on Tradier for Greeks

Free price-data APIs are abundant (Alpaca, Polygon free, Twelve Data 800 calls/day, yfinance) but almost none give option Greeks for free. **Tradier’s free developer/sandbox account returns full chains with delta, gamma, theta, vega, rho and IV inline (Greeks courtesy of ORATS).** Tradier’s official Get Options Chains docs state plainly: “Greek and IV data is included courtesy of ORATS.” ORATS’ own announcement describes the partnership feed as providing “options bid-ask prices, greeks, theoretical values…for all stocks, ETFs, and indexes” via a **live (real-time) feed** — not a strictly hourly refresh as sometimes assumed. yfinance gives option chains but **only `impliedVolatility` — no Greeks**: this is GitHub issue #1465 on ranaroussi/yfinance (“Display the greeks when returning options data,” opened Mar 26, 2023), which was **closed as “not planned,”** so Greeks will not be added — you must compute them yourself (Black-Scholes/QuantLib) if you rely on yfinance. yfinance is also increasingly rate-limited (HTTP 429 `YFRateLimitError`, widespread across 2025 with multiple open repo issues). DXY is not free on most APIs but yfinance serves the ICE index as `DX-Y.NYB` (or use the **UUP** ETF / `DX=F` futures as proxies).

### D. News avoidance is a solved, free problem

ForexFactory publishes a weekly calendar at `https://nfs.faireconomy.media/ff_calendar_thisweek.xml` (also `.json`, `.csv`, `.ics`) with event title, country, date/time, and impact (High/Medium/Low). **Critical limit (FF forum thread #1311021): “As of August 2024, ForexFactory now limits the downloading of weekly news file(s) to a maximum of 2 every 5 minutes, regardless of the file type chosen (.xml .json .ics .csv)”** — a March 2025 update notes FF then moved to *independent* 2-per-5-minute limits for each of the four file types. Practical rule either way: download once, cache locally, reuse all week. Cross-check FOMC/NFP/CPI/PPI with the FRED release calendar or the official White House “Principal Federal Economic Indicators” schedule. Roll Call (rollcall.com) offers a free downloadable annual Congressional session/recess PDF calendar but **no public API** (structured data is behind the paid CQ subscription).

-----

## Details

### PART 1 — ICT CONCEPTS WITH DETECTION LOGIC

Define globally first:

- **Swing high**: candle whose high is greater than the highs of the `k` candles immediately before and after it  (k=2 default; k=3 for HTF). **Swing low**: mirror. Use these as structure pivots.
- **Displacement**: an impulsive move; flag a candle/leg as displacement if its body ≥ 1.5 × ATR(10) **and/or** it creates an FVG. Displacement is what separates a real structural break from a wick probe.
- **Premium/Discount/Equilibrium**: within any dealing range (swing low → swing high), 50% = equilibrium; above = premium (sell zone), below = discount (buy zone).  Buys are sought in discount, sells in premium.

**1. Break of Structure (BOS) — continuation.**

- Bullish BOS: in an uptrend (series of higher highs/higher lows), price closes a candle body **above** the most recent confirmed swing high. Bearish BOS: body close **below** the most recent swing low.
- Detection: track the last confirmed swing high/low; on each new close, if close > last_swing_high → bullish BOS (trend continues up). Require a **body close**, not a wick, to filter stop-runs. 

**2. Market Structure Shift (MSS) / Change of Character (CHoCH) — reversal.**

- In ICT use these as near-synonyms (ICT himself: “you can consider them the same”).  Practical distinction: CHoCH = first counter-trend break (early warning); MSS = the counter-trend break accompanied by **displacement** (confirmed). 
- Bullish MSS: during a downtrend (lower highs/lows), price breaks **above** the most recent lower high **with displacement**. Bearish MSS: breaks below the most recent higher low with displacement.
- Detection: in a downtrend, mark the most recent swing high (the lower high). If a candle closes above it AND that breaking leg qualifies as displacement (body>1.5×ATR or leaves FVG) → bullish MSS. This is the core reversal trigger for entries.

**3. Liquidity (BSL/SSL), pools, equal highs/lows, sweeps/raids, stop hunts.**

- **Buy-side liquidity (BSL)**: resting buy-stops **above** old highs / equal highs / prior-day high / prior-week high. **Sell-side liquidity (SSL)**: sell-stops **below** old lows / equal lows / PDL / PWL.
- **Equal highs/lows**: two or more swing highs (or lows) within a small tolerance band (e.g., within 0.05–0.10% of price, or within ~0.1×ATR) → flag as an engineered liquidity pool.
- **Liquidity sweep / raid / stop hunt**: price wicks **beyond** a known pool (old high/low or equal H/L) and then **reverses back through the level** (the breaking candle closes back inside). Detection: `high > pool_level` (BSL) but `close < pool_level` within 1–3 candles → bullish-context sweep of BSL (often precedes a down move); mirror for SSL sweep (precedes up move). The reversal — not the poke — is what defines a sweep vs. a run.
- **Rule of thumb to encode**: in a bullish HTF bias, expect a **sweep of SSL (below an old low)** before continuation up; in bearish bias, expect a **sweep of BSL** before continuation down.

**4. Fair Value Gap (FVG) / imbalance — exact 3-candle definition.**

- **Bullish FVG (BISI)**: 3 consecutive candles where `low[candle3] > high[candle1]` — the gap is the zone between candle-1 high and candle-3 low; middle candle is the displacement candle. **Bearish FVG (SIBI)**: `high[candle3] < low[candle1]`.
- Pine-equivalent logic: `bull_fvg = low > high[2]`; `bear_fvg = high < low[2]` (indexing current candle as candle 3).
- **Consequent Encroachment (CE)** = the 50% midpoint of the gap = (top+bottom)/2; ICT’s “ideal fill” entry level.
- Validity filter: require the middle/displacement candle body to exceed ATR (displacement-grade), discard micro-gaps. Mark FVG “mitigated/filled” once price trades back through it. (An **Inversion FVG / IFVG** is a failed FVG that flips polarity after a confirmed body close beyond it.)

**5. Order Blocks (bullish/bearish).**

- **Bullish OB**: the **last down-close (bearish) candle before** an up-move that breaks structure. Zone = that candle’s low-to-high (some use body only). **Bearish OB**: the last up-close candle before a down-move. 
- ICT validity (4 conditions): (a) the impulse leg engulfs/takes the OB candle’s opposite extreme, (b) closes beyond the OB body, (c) leaves an **imbalance/FVG** on the lower timeframe, (d) produces a **structure shift (MSS)**. An OB with an adjacent FVG is far stronger.
- Entry: on retrace into the OB zone; the highest-probability trigger is a **lower-timeframe MSS at the OB tap**, not the tap alone. Stop beyond the OB extreme + buffer.
- **Breaker block**: a failed OB — price sweeps liquidity, fails the OB, closes through it, and shifts structure; the broken OB then acts from the opposite side (failed bullish OB → resistance).

**6. Optimal Trade Entry (OTE) — Fibonacci.**

- Anchor the Fib on the **impulse/displacement leg** (bullish: swing low→swing high; bearish: swing high→swing low). Plot body-to-body for stability.
- **OTE zone = 62%–79% retracement; 70.5% (0.705) is the “sweet spot” central level.** 0.5 = equilibrium.
- Standard-deviation profit projections ICT uses: -0.27, -0.62, -1.0, -2.0, -2.5, -4.0.
- Entry rules: only take OTE in the direction of HTF bias; require confluence inside the 62–79% zone (an FVG, OB, or equal-liquidity). Stop just beyond the 1.0 (the swing origin / sweep extreme) + buffer. Invalidation = a candle **body** close beyond the 1.0 level (wicks through don’t invalidate).

**7. Market Maker Models (MMXM = MMBM buy / MMSM sell).**

- Four phases (V-shape for buy model, inverted-V for sell): **(1) Original Consolidation** (range where liquidity builds); **(2) Engineering Liquidity** (a counter move printing higher-lows [MMSM] or lower-highs [MMBM] that stack stops); **(3) Smart Money Reversal (SMR)** at an HTF PD array — confirmed by MSS + often SMT divergence; **(4) Liquidity Hunt / distribution** sweeping the engineered stops, then the original-consolidation extreme, then the HTF draw-on-liquidity.
- **MMBM** = price travels from a bullish (discount) PD array up to a bearish (premium) PD array, sweeping highs. **MMSM** = bearish PD array down to bullish PD array, sweeping lows. Build it on HTF (Daily/4H for swing), execute on 15m/5m.
- Profit targets: engineered old highs/lows first → original-consolidation extreme → HTF draw on liquidity. ICT also projects targets with Fib 1 to -2.5 from SMR to MSS. 

**8. Killzones / time windows (all New York / ET; shift with US DST — anchor to ET).**

- **London Open**: 02:00–05:00 ET (London Silver Bullet 03:00–04:00).
- **New York AM (indices)**: 08:30–11:00 ET (forex NY KZ often 07:00–10:00).
- **NY AM Silver Bullet**: 10:00–11:00 ET (the single highest-probability hour).
- **London Close**: 10:00–12:00 ET (reversals/profit-taking).
- **NY PM session**: ~13:30–16:00 ET.
- **Asian range**: ~20:00–00:00 ET (builds the range London targets).
- For **swing** trading, killzones matter less for entry timing than for *where the daily candle’s high/low forms*; use them to time the LTF entry trigger but the trade is held across sessions/days. NY AM is the dominant window for US indices/stocks.

**9. DXY inverse correlation & SMT divergence.**

- **DXY bias rule**: DXY up → risk/equities (SPX, QQQ, NVDA, etc.) pressured down, and vice versa (inverse). Use DXY’s own ICT structure (is DXY sweeping a high then reversing down?) as a confirming/leading tilt for a long-equities bias. Correlations decouple — use as confirmation, **not** a standalone signal.
- **SMT (Smart Money Technique) divergence**: compare two correlated instruments at a swing. Positively correlated (e.g., **SPX/ES vs NQ/QQQ**, or NVDA vs SOX/peers): bullish SMT = one makes a lower low while the other makes a higher low (the one refusing to break is strong). Bearish SMT = one makes a higher high, the other a lower high. For **negatively** correlated pairs (equities vs DXY): at a turning point, equities make a lower low while DXY fails to make a higher high (or vice versa) → divergence flags manipulation/reversal. ICT originally introduced SMT (2022) for NQ vs ES. Detection: at the moment instrument A prints a new swing extreme, check whether correlated instrument B confirms; non-confirmation at an HTF PD array = SMT.

**10. HTF bias & multi-timeframe (swing).**

- Top-down, never bottom-up: **Weekly → Daily (macro bias) → 4H (zone/PD array) → 1H/15m (entry trigger)**. ICT’s prescribed swing trio is **Daily, 4H, 1H**. Daily sets bias (structure + the 2017 video’s 10/20 EMA stack + draw-on-liquidity), 4H locates the OB/FVG zone, 1H/15m gives the MSS + FVG/OTE entry.
- **Daily bias heuristics to encode**: mark prior-day & prior-week high/low; if SSL was recently swept, next draw is likely BSL (and vice versa); “failed displacement” / next-day model — a swept level that closes back inside flags reversal for the next session.

### PART 2 — TECHNICAL BUILD (free/low-cost, accurate, easy)

**Recommended stack: Python.** Core libs: `pandas`, `numpy`, `requests` (Tradier REST), `yfinance` (DXY), `python-telegram-bot` or raw Telegram Bot API via `requests`, `APScheduler`/`schedule` (or external cron/GitHub Actions), `pandas-ta` if you want EMA/ATR helpers (or compute inline). No `ccxt` (not crypto).

**Price/OHLCV data — comparison:**

- **Tradier (RECOMMENDED primary)**: free developer/sandbox key, no funded account needed. REST `/markets/history` (daily) and `/markets/timesales` (intraday: 1/5/15-min). Quotes delayed ~15 min in sandbox. Covers stocks/ETFs/indices incl. SPX, NVDA, PLTR, AMD, TSLA, QQQ. Same vendor for options → one integration. **Rate limits ~120 requests/minute for most endpoints (higher for market data), and batch quote requests allow up to 100 symbols per call** — encode this in the scanner’s polling loop. $0.35/contract only matters if you later trade live.
- **Alpaca**: excellent free intraday equity/ETF bars; clean API; **no options Greeks, no index (SPX) data, no futures.** Good secondary for stock/ETF candles.
- **Polygon free**: end-of-day only, 5 calls/min — too limited for intraday; paid tiers strong.
- **Twelve Data**: free 800 calls/day, 8/min; global coverage; good fallback for candles/indices.
- **Finnhub**: generous 60 calls/min free; has an economic-calendar endpoint too.
- **yfinance**: free, easy, daily+intraday (1m limited to ~7 days, 15m/1h to ~60 days); **unofficial scraper, increasingly rate-limited (429) in 2025** — fine as a DXY source and backup, not as the production backbone.
- **Alpha Vantage**: 25 calls/day free — too tight. **EODHD**: ~€20/mo, EOD-focused.

**DXY specifically:** `yfinance.Ticker("DX-Y.NYB")` (ICE US Dollar Index, daily/weekly reliable; intraday spotty). Proxies if needed: **UUP** ETF (tradable, available on Tradier/Alpaca with full intraday), or `DX=F` (ICE DXY futures via yfinance). For ICT structure on the dollar, daily/4H DXY via `DX-Y.NYB` is sufficient; use UUP if you need clean intraday.

**Options chains + Greeks:**

- **Tradier (RECOMMENDED)**: `/markets/options/chains?symbol=...&expiration=...&greeks=true` returns per-strike `delta, gamma, theta, vega, rho, phi, bid_iv, mid_iv, ask_iv` (ORATS-supplied live feed) plus bid/ask/volume/OI. `/markets/options/expirations` and `/markets/options/lookup` for roots. Handles weekly roots (SPXW, RUTW) via `includeAllRoots`.
- **yfinance**: `Ticker.option_chain()` returns calls/puts with `impliedVolatility` only — **no Greeks** (issue #1465 closed “not planned”; must compute via Black-Scholes/QuantLib). Use only as backup.
- **Others**: Polygon options (paid), CBOE (delayed/limited free), Schwab/IBKR (require funded accounts).
- For this system, Tradier alone covers quotes + chains + Greeks for all target tickers.

**Cash-settled index options (encode these contract facts):**

- **SPX**: European-style, **cash-settled**, Section 1256 (60/40 tax), $100 multiplier, no early assignment, no pin risk. AM-settled monthly (`SPX`) vs PM-settled weeklies (`SPXW`).
- **XSP (Mini-SPX)**: 1/10th SPX notional, European, cash-settled, Section 1256 — best index choice for smaller accounts; lower liquidity than SPX/SPY (watch spreads).
- **QQQ**: an **ETF** option — **American-style, physically settled (shares), standard equity tax, early-assignment/pin risk.** Same caveat for NVDA/PLTR/AMD/TSLA single-name options. Encode: index options (SPX/XSP) = cash/European/1256; equity & ETF options (QQQ + single names) = American/physical/standard tax.

**Contract selection logic (for the alert):**

- DTE: **7–14 days minimum** (the user’s spec) — long enough to limit theta bleed on a multi-day swing.
- Greeks targeting: directional swing → **delta ≈ 0.45–0.65** (ATM to slightly ITM gives positive expectancy with manageable theta); avoid far-OTM (delta <0.30) lottery tickets for 1:1 R:R. Flag **theta** as % of premium/day and **IV** (avoid buying into elevated IV before known events).
- Sizing for **1:1 R:R**: define stop in the underlying (beyond the sweep/OB), target at next liquidity pool or a 1:1 move; translate underlying move → option P/L via delta (and gamma for larger moves). Alert should show: strike, expiry, delta/theta/vega, est. debit, and the underlying stop/target levels.

**News sourcing:**

- **ForexFactory**: `https://nfs.faireconomy.media/ff_calendar_thisweek.xml` (or `.json`). Parse `<event>` with `title, country, date, time, impact`. **Filter for `country=USD` and `impact=High`.** Rule: suppress new entry alerts within a configurable window (e.g., **24h before through 2h after** a High-impact USD event for swing, or tighter ±30–60 min for the underlying day). **Download once/week and cache** (FF limit: 2 downloads/5 min per file type).
- **FRED release calendar** (`fred.stlouisfed.org/releases/calendar`) and the White House “Principal Federal Economic Indicators” 2026 PDF for authoritative FOMC/NFP/CPI/PPI dates; **Finnhub `/calendar/economic`** as a programmatic option.
- **Roll Call**: free downloadable 2026 Congressional session/recess PDF (`rollcall.com/congressional-calendar/`) for political-risk windows (e.g., the Jan 30 2026 funding deadline, election recess) — **no public API**; parse the PDF once or hand-maintain key dates.

**Hosting/scheduling (free→cheap):**

- **GitHub Actions cron**: free minutes are **2,000/month for private repos on the Free plan (Team 3,000, Enterprise 50,000) — and unlimited for public repositories** (Linux overage $0.008/min; macOS billed 10×, Windows 2×). Run the scanner every 15–30 min during market hours via `on: schedule: - cron:`. Note GitHub cron is imprecise (can lag minutes) and times are UTC — fine for swing. Store API keys as encrypted Actions secrets.
- **Local + cron/APScheduler** or a **$5/mo VPS** (DigitalOcean/Hetzner) for reliability and persistent state.
- **Alerts**: **Telegram Bot API** (create via @BotFather, `requests.post` to `/sendMessage`) — simplest, free, rich formatting. **Discord webhook** (copy webhook URL, POST JSON) equally easy. **SMTP email** as fallback. Telegram recommended.

### PART 3 — SYNTHESIS: alert system logic (pseudocode the agent should implement)

```
For each ticker in [SPX, XSP, QQQ, NVDA, PLTR, AMD, TSLA]:
  1. HTF BIAS (Daily, then 4H):
     - Compute structure (swing highs/lows → uptrend/downtrend) + daily 10/20 EMA stack.
     - Require a CLEAR direction (structure and EMA agree). Else skip ticker.
  2. DXY / SMT CROSS-CHECK:
     - Pull DXY (DX-Y.NYB) + a correlated index (SPX vs QQQ; single names vs SPX/SOX).
     - Confirm equity bias against DXY inverse structure; look for SMT divergence at the PD array.
     - If DXY structure contradicts the equity bias strongly → downgrade/skip.
  3. ZONE (4H): locate the nearest in-bias PD array (bullish OB or bullish FVG in discount for longs).
  4. LTF ENTRY TRIGGER (1H/15m):
     a. Liquidity sweep of SSL (for longs) / BSL (for shorts) — wick beyond pool + close back inside.
     b. MSS with displacement in bias direction.
     c. Entry confluence: price in OTE 62–79% (0.705) AND/OR tapping the OB/FVG (CE = 50% of FVG).
  5. RISK (1:1):
     - Stop = beyond the sweep extreme / OB far edge (+ buffer).
     - Target = next liquidity pool (old high/low, equal H/L) OR a 1:1 distance, whichever defines R:R>=1:1.
  6. NEWS FILTER:
     - If High-impact USD event within window -> HOLD alert (flag "news risk").
  7. CONTRACT SELECTION:
     - Tradier chain, expiry 7-14 DTE, delta 0.45-0.65, acceptable IV/theta.
     - Index (SPX/XSP) = cash/European/1256 note; ETF/equity = American/assignment note.
  8. EMIT ALERT (Telegram): ticker, direction, bias rationale (HTF structure + DXY/SMT),
     sweep/MSS/zone detail, entry level, stop, target, R:R, suggested contract
     (strike/expiry/Greeks/est. debit), and any news caveat. NEVER auto-execute.
```

### A drop-in coding-agent prompt (hand this to Claude Code)

> Build a Python 3.11 **alert-only** (no execution) swing-options scanner for SPX, XSP, QQQ, NVDA, PLTR, AMD, TSLA implementing ICT (Inner Circle Trader) logic.
> **Data**: Tradier sandbox REST for OHLCV (`/markets/timesales` 15m/1h, `/markets/history` daily) and options chains with Greeks (`/markets/options/chains?greeks=true`); respect 120 req/min and batch quotes ≤100 symbols. yfinance `DX-Y.NYB` for the US Dollar Index (fallback to UUP via Tradier). ForexFactory weekly XML (`nfs.faireconomy.media/ff_calendar_thisweek.xml`) cached once/week for High-impact USD events.
> **Modules**: `structure.py` (fractal swing detection k=2/3; BOS, MSS/CHoCH with displacement = body≥1.5×ATR(10) or leaves FVG), `liquidity.py` (BSL/SSL pools, equal highs/lows within 0.1×ATR, sweep = wick beyond + close back inside), `pdarrays.py` (FVG bull `low>high[2]`/bear `high<low[2]` with CE midpoint; order blocks with 4-condition validity; breaker blocks), `ote.py` (Fib 62/70.5/79 on the impulse leg, premium/discount), `bias.py` (Daily structure + 10/20 EMA stack; 4H zone; 1H/15m trigger), `smt.py` (cross-asset divergence + DXY inverse check), `news.py` (FF XML parse + filter window), `contracts.py` (pick 7–14 DTE, delta 0.45–0.65, label SPX/XSP as cash/European/1256 vs QQQ/single-names as American/physical), `alert.py` (Telegram Bot API sendMessage), `main.py` (the Part-3 pipeline). Schedule via GitHub Actions cron (or APScheduler locally). Emit a structured alert with full reasoning, entry/stop/target, R:R≥1:1, and suggested contract. Unit-test BOS/MSS/FVG/OB on historical daily+1H data before going live. Keep a human in the loop — never auto-trade.

## Recommendations

1. **Build v1 on Tradier + Telegram + ForexFactory XML, scheduled on GitHub Actions.** This is $0, covers price + Greeks + news + alerts, and integrates in one API. Validate against TradingView ICT indicators (FibAlgo/LuxAlgo FVG, OB, SMT scripts) for parity before trusting signals. (If you keep the repo public, GitHub Actions minutes are unlimited free.)
1. **Codify the two primitives first (swing pivots k=2/3, displacement = body≥1.5×ATR or leaves FVG), then unit-test BOS/MSS/FVG/OB detection on historical daily+1H data** for each of the 7 tickers. Everything downstream depends on these.
1. **Start the universe with SPX/XSP/QQQ** (cleaner ICT behavior, index liquidity, and XSP for small accounts/1256 tax) before adding the higher-beta single names (NVDA/PLTR/AMD/TSLA), which sweep more erratically.
1. **Keep the human in the loop.** Emit setups with full reasoning and a confidence score; require manual confirmation. ICT bias and “displacement” are partly judgmental.
1. **Thresholds that change the plan**: if Tradier sandbox 15-min delay or rate limits hurt, upgrade to Tradier production data or add Alpaca for equity candles; if yfinance DXY 429s, switch to UUP via Tradier; if FVG/OB signal quality is poor on single names, restrict to indices and require SMT confirmation.

## Caveats

- **Sources skew to third-party ICT explainers** (innercircletrader.net, tradingfinder, luxalgo, TradingView scripts) and near-verbatim lecture-note transcriptions (Studocu) rather than ICT’s primary videos; concepts are internally consistent across them but ICT has revised terminology over the years (e.g., “draw on liquidity” is post-2020).
- **The 2017 “Secrets To Swing Trading” video specifically teaches daily 10/20-EMA bias + H1 OTE entries; it does NOT cover weekly bias, “draw on liquidity,” or explicit multi-day hold rules** — those come from his later (2022+) material. The synthesized swing model here blends both eras.
- **ICT is unproven as a systematic edge.** Several explainer sites carry marketing/affiliate framing; “smart money/algorithm” narratives are interpretive, not established market microstructure fact. Detection of swing points, displacement, and bias involves subjective thresholds; backtest before risking capital.
- **Data limits**: Tradier sandbox quotes are ~15-min delayed (fine for swing, not scalping); yfinance is rate-limited and unofficial (and provides no option Greeks); ForexFactory throttles downloads (cache weekly). ORATS Greeks via Tradier come from a live feed but should be treated as reference, not execution-grade.
- **Tax/contract specifics** (Section 1256, settlement style) are general and not tax advice; confirm with a professional. Options trading carries substantial risk; a 1:1 R:R on long premium still loses to theta if the move stalls.
