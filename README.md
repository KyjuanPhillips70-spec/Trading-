# Trading-
Alert
# ICT Swing-Options Alert System — Read Me (Plain English)

This file is for **you**, the owner — not the coding agent. It explains, in plain language, what this thing is, what each piece does, and how to run a manual test from your phone. (The agent has its own detailed instructions in `BUILD_SPEC.md`.)

-----

## What this is

A small program that watches a fixed list of tickers and sends you a **Telegram message** whenever it spots a swing-trade options setup that matches ICT (Inner Circle Trader) rules. It does **not** place trades. Every alert is a *suggestion* — you read it and decide.

**Tickers it watches:**

- Index / broad market: **SPX, XSP, QQQ**
- Tech & momentum: **NVDA, PLTR, AMD, TSLA**

**What an alert gives you:** direction (long/short), the reasoning, an entry price, a stop, a target at 1:1 risk/reward, and a specific option contract to consider (at least 7 days out, with healthy Greeks).

-----

## The non-negotiable rules it follows

The system will **never** alert unless ALL of these are true:

1. Clear market direction on **both the 4-hour and 1-hour** charts (for indices/ETFs).
1. That direction agrees with the **US Dollar Index (DXY)** — dollar up usually means stocks down, and vice versa.
1. A lower-timeframe **entry trigger**: price grabs liquidity (a stop sweep), then **breaks structure**, then offers an entry in a quality zone (Fair Value Gap, Order Block, or the OTE Fibonacci pocket).
1. The trade is at least **1:1 risk to reward**.
1. The suggested option is **7–14 days to expiration** with a delta around **0.45–0.65** (not a long-shot lottery ticket).
1. **No major USD news** is due inside the blackout window (it avoids trading into things like FOMC, CPI, NFP).

-----

## What each piece does (the tour)

Think of it as an assembly line. Each part does one job and hands off to the next.

- **The data fetchers** — pull price candles, option chains (with Greeks), the dollar index, and the news calendar.
  - *Tradier* gives prices and option data including the Greeks. (Free sandbox account.)
  - *Yahoo (yfinance)* gives the dollar index; if that hiccups, it falls back to the UUP ETF as a stand-in.
  - *ForexFactory* gives the weekly news calendar (downloaded once and reused all week).
- **The “primitives”** — the basic vision: finding swing highs/lows and spotting an *impulsive* move (called “displacement”). Everything else is built on these.
- **Structure** — decides if the trend is up or down, and detects a **Break of Structure** (trend continues) or a **Market Structure Shift** (trend flips).
- **Liquidity** — finds where stop-losses are resting (above old highs / below old lows) and detects when price **sweeps** them and snaps back. ICT’s whole idea is that price hunts these pools before the real move.
- **PD arrays** — finds the high-quality entry zones: **Fair Value Gaps** (price imbalances) and **Order Blocks** (the last candle before a big move).
- **OTE** — the Fibonacci “discount” pocket (62%–79%) where ICT likes to enter on a pullback.
- **Bias** — looks at the daily and 4-hour charts (structure + a 10/20 EMA “stack”) to decide the overall lean, then checks the lower timeframes for the trigger.
- **SMT** — cross-checks two related markets (e.g., SPX vs QQQ, or a stock vs the index) and the dollar to catch divergences that hint at a turn.
- **News** — blocks alerts around high-impact USD events.
- **Contracts** — picks the actual option: right expiration, right delta, liquid, and labels whether it’s cash-settled (SPX/XSP) or share-settled (QQQ and the single stocks).
- **Risk** — sets the stop (just past the sweep) and the target (next liquidity pool or 1:1), and estimates what the option might gain or lose.
- **The scanner + alert** — runs all of the above for each ticker and, if everything lines up, sends the Telegram message.

-----

## How it runs by itself

GitHub runs the program on a schedule (every ~20 minutes during market hours) in the cloud. You don’t need a computer on. When a setup appears, your phone buzzes with the alert. That’s it.

-----

## Your four secret keys

These live in GitHub’s encrypted “Actions secrets” (never in the code, never visible):

- `TRADIER_TOKEN` — from your Tradier developer account
- `TELEGRAM_BOT_TOKEN` — from @BotFather in Telegram
- `TELEGRAM_CHAT_ID` — from @userinfobot in Telegram
- (`TRADIER_BASE_URL` is preset to the sandbox URL)

-----

## How to run a manual test (from your phone)

You don’t have to wait for the schedule. Once the build is done and your secrets are saved:

1. In your repo, tap the **Actions** tab.
1. Pick the **ict-scan** workflow.
1. Tap **Run workflow** (the manual trigger).
1. Watch the run. Green check = it ran. Tap into the run to read the log.
1. If a setup was found, the alert lands in **Telegram**. If not, the log will say “no setups” — that’s normal; good setups are rare by design.

**To prove alerts work even when there’s no setup:** ask the agent (Claude Code on the web) to *“add a `--test-alert` flag to main.py that sends one sample Telegram message so I can confirm delivery.”* Run that once; you should get a test message on your phone.

-----

## When something doesn’t work

The normal fix-it loop, all from your phone:

1. Open the failed run in the **Actions** tab and copy the red error text.
1. Paste it to **Claude Code on the web** with: *“This run failed with this error — please fix it.”*
1. It patches the code and opens a PR; you merge it and re-run.

Common first-time snags: a key typo in Actions secrets, or the sandbox needing a data domain allowed. The agent knows how to handle both.

-----

## Honest expectations

- This mechanizes a sensible reading of ICT, but ICT is **discretionary and unproven as a pure system**. Treat alerts as candidates, not commands. Paper-trade or backtest before risking real money.
- Sandbox prices are delayed ~15 minutes — fine for multi-day swings, not for scalping.
- A 1:1 options trade still loses to time decay if the move stalls. Mind the expiration.
- Nothing here is financial advice.
