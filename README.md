# Paper Terminal — NSE dual-dashboard paper-trading app

> **PAPER TRADING ONLY — NO LIVE ORDERS.**
> This application never places, modifies or cancels a real order. It has no live-trading switch,
> no broker order code, and no setting that can enable one. Dhan is used only for read-only market
> data. Every entry, exit, stop, target, position and P&L figure is simulated by an internal engine.

Two independent dashboards share one market-data layer, one database and one paper-execution engine,
but use **separate strategies and separate paper ledgers**:

| | Dashboard 1 — MTF Paper Trading | Dashboard 2 — Mechanical Swing Scanner |
|---|---|---|
| Universe | Nifty 100 | Nifty LargeMidcap 250 ("Nifty 250") |
| Strategy | Multi-timeframe baseline (Daily → 4H → 15m → 5m) | Mechanical Swing Trading System, rules A–H |
| Trade levels | Entered by you (entry, stop, target, allocation) | Calculated by the strategy (read-only; overrides are labelled) |
| Min reward:risk | 1:2 | 1:3 |
| Paper account | `D1_MTF`, ₹1,00,000 | `D2_MECH`, ₹1,00,000 |

---

## Contents
1. [Requirements](#1-requirements)
2. [Architecture](#2-architecture)
3. [Install on macOS / Linux](#3-install-on-macos--linux)
4. [Install on Windows](#4-install-on-windows)
5. [Start the application](#5-start-the-application)
6. [First-time setup (credentials, universes)](#6-first-time-setup)
7. [Dashboard 1 — MTF strategy and auto trade](#7-dashboard-1--mtf-paper-trading)
8. [Dashboard 2 — Mechanical Swing scanner](#8-dashboard-2--mechanical-swing-scanner)
9. [Paper-trading engine](#9-paper-trading-engine)
10. [TradingView charts](#10-tradingview-charts)
11. [OpenAI explanations](#11-openai-explanations)
12. [Tests](#12-tests)
13. [Database backup and reset](#13-database-backup-and-reset)
14. [Security](#14-security)
15. [API costs and limits](#15-api-costs-and-limits)
16. [Troubleshooting](#16-troubleshooting)
17. [Strategy interpretation notes](#17-strategy-interpretation-notes)
18. [Known limitations](#18-known-limitations)
19. [No-live-trading verification](#19-no-live-trading-verification)

---

## 1. Requirements

| Tool | Version |
|---|---|
| Python | 3.11 – 3.13 (developed and tested on 3.13; 3.12 recommended) |
| Node.js | 20 or 22 LTS (tested on 22) |
| npm | 10+ |
| A Dhan account | with **Data APIs** enabled for candles and quotes |
| OpenAI API key | optional, only for AI explanations |

## 2. Architecture

```
backend/                     FastAPI + SQLAlchemy + APScheduler (Python)
  app/main.py                app factory, migrations on startup, scheduler lifecycle
  app/api/                   routes_dashboard1/2, routes_paper_trades, routes_settings, routes_system
  app/core/                  config, security (encryption/masking), scheduler, NSE calendar, logging
  app/integrations/          dhan_client (read-only, whitelisted), openai_client, tradingview
  app/market_data/           candle parsing/validation/4H aggregation, instruments, freshness, cache
  app/strategies/            dashboard1_mtf.py, dashboard2_mechanical.py, indicators.py
  app/paper_trading/         engine (ledger), execution (fill rules), risk_manager, charges, position_manager
  app/services/              universe, scan, signal, mtf, settings, market data, explanations
  app/database/              models, session, repository, Alembic migrations
  tests/                     143 pytest tests (external APIs mocked; synthetic data only in tests)
frontend/                    React 18 + TypeScript + Vite + Tailwind + TradingView Lightweight Charts
  src/pages/                 Dashboard1, Dashboard2, PaperTradeBook, TradeHistory, Settings, SystemStatus
  src/components, charts/    shared UI, modals, chart panel, TradingView widget
data/                        SQLite DB, encryption key, scrip-master cache, nse_holidays.json
scripts/                     start scripts (sh/ps1), db_tools.py (backup/reset)
```

The frontend never decides cash, quantity, fills or risk: it calls `/preview` endpoints and displays the
backend's numbers. Live dashboard updates use HTTP polling (React Query, 2–20 s); no WebSocket/SSE.

## 3. Install on macOS / Linux

```bash
git clone <this repo> && cd Propips_Dashbaord

# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..

# Frontend
cd frontend
npm install
cd ..
```

## 4. Install on Windows

PowerShell:

```powershell
cd Propips_Dashbaord\backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..\frontend
npm install
```

If script execution is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 5. Start the application

The database (`data/trading.db`) is created and migrated automatically (Alembic) on first backend start;
no manual database setup is needed.

**Option A — development (two terminals):**

```bash
# terminal 1 — API on http://127.0.0.1:8000
cd backend && source .venv/bin/activate && python run.py
# terminal 2 — UI on http://127.0.0.1:5173
cd frontend && npm run dev
```

Open **http://127.0.0.1:5173**. Windows: `.\.venv\Scripts\python.exe run.py` and `npm run dev`, or use
`scripts\start_backend.ps1` / `scripts\start_frontend.ps1`. macOS/Linux helpers: `scripts/start_backend.sh`,
`scripts/start_frontend.sh`.

**Option B — single process:** `cd frontend && npm run build`, then start the backend; it serves the built UI
at **http://127.0.0.1:8000**.

**Option C — Docker (untested in the build environment):** `docker compose up --build`, then open
http://127.0.0.1:8000. Data persists in `./data`.

Both servers bind to `127.0.0.1` only. Optional overrides go in `backend/.env` (see `.env.example`):
`PT_PORT`, `PT_DATABASE_URL`, `PT_ENABLE_SCHEDULER`, `PT_DEFAULT_INITIAL_CAPITAL`.

Starting the app does **not** mean any external API works. Check **System Status** and use the
connection tests.

## 6. First-time setup

Open **Settings & API Credentials**.

### 6.1 Dhan Client ID and access token
1. In Dhan web: *My Profile → Access DhanHQ APIs* → generate an access token. Make sure Data APIs are active.
2. Enter the **Client ID** → *Save*. It becomes read-only; changing it later requires *Edit Client ID* and a confirmation.
3. Paste the **Access token** → *Save*. It is stored encrypted and shown masked (last 4 characters).
4. Click **Test Dhan Connection**. The app calls `GET /v2/profile`, then a `POST /v2/marketfeed/ltp` probe on
   one mapped instrument, and records one of: `CONNECTED`, `AUTH_FAILED`, `PERMISSION_DENIED`, `RATE_LIMITED`,
   `NETWORK_ERROR`, `MARKET_DATA_UNAVAILABLE`. Saving alone sets the status to `UNTESTED`.

**Token updates:** web-generated Dhan tokens are typically valid for up to 24 hours. The app shows a reminder
when the saved token is older than 24 h. This is a reminder only, not an expiry rule, and there is no
automatic refresh. The real validity is shown from Dhan's `/profile` (`tokenValidity`) after a test. Use
*Update / Replace token* to paste a new one.

### 6.2 Universes (Nifty 100 and Nifty 250)
In **Universes & instrument mapping**, in this order:
1. **Dhan scrip master** → *Download from Dhan* (`images.dhan.co/api-data/api-scrip-master.csv`, public) or *Upload CSV*.
2. **Nifty 100** → *Download official list* (`niftyindices.com/IndexConstituent/ind_nifty100list.csv`) or upload it.
3. **Nifty 250** → *Download official list* (`ind_niftylargemidcap250list.csv`) or upload it.

Each sync records its time, source, count, additions and removals. Symbols not found in the scrip master
(matched by symbol, then ISIN to catch renames) are flagged `MISSING_IN_SCRIP_MASTER` and skipped by scans.
Nothing is hard-coded. If NSE blocks automated downloads from your network, download the CSV in a browser
and upload it. Re-sync whenever NSE rebalances the indices (semi-annually).

### 6.3 Paper accounts
Both accounts start with ₹1,00,000 of simulated cash. Under **Paper accounts & risk limits** you can change
limits and reset an account (type `RESET`; open positions must be closed first; the initial capital is configurable).

## 7. Dashboard 1 — MTF paper trading

### 7.1 Table
Price, change and % change come from Dhan `/marketfeed/ohlc` REST snapshots, refreshed every minute during
the session. They are labelled `RECENT_SNAPSHOT` (≤ 2 min), `DELAYED_SNAPSHOT` (≤ 10 min), `STALE`, or
`LAST_AVAILABLE` (market closed), and are never called "live". The MTF columns are refreshed every 15 minutes
during the session, or immediately with *Refresh MTF now*.

Filters: search (symbol or company), MTF bias, confirmation status, auto-trade enabled, open positions.
Sorting: symbol, price, change, % change, MTF quality, unrealized P&L. *Reset filters* clears all of them.

### 7.2 Strategy definition (`app/strategies/dashboard1_mtf.py`)
All checks use **completed candles only**. 4H candles are built from Dhan 60-minute candles in two
session-anchored buckets (09:15–13:15, 13:15–15:30), because Dhan has no native 4H interval.

| TF | Condition (BUY) |
|---|---|
| Daily | `close > EMA50` **and** `EMA50[t] > EMA50[t−5]` (rising) |
| 4H | `close > EMA20 > EMA50` **and** no bearish reversal: `close ≥ low of the latest confirmed swing low` (pivot 2/2) |
| 15m | `close > EMA20` **and** `EMA20[t] > EMA20[t−3]` |
| 5m | the configured entry trigger fires on a completed 5m candle |
| Data | Daily, 4H and 15m must be `FRESH` (missing → `UNAVAILABLE`, never assumed) |

MTF bias = BULLISH if Daily and 4H are bullish, BEARISH if both are bearish, otherwise NEUTRAL.
Dashboard 1 does **not** use Fibonacci, 3-red-candle, demand-zone or 1:3 rules.

### 7.3 Enable Auto Trade
The modal shows the stock's chart, a live MTF evaluation with candle times and freshness, and these inputs:
fund allocation, entry (manual, or *Use latest price*, which is never applied silently), stop, take profit,
optional max monetary risk, and the entry trigger:

* `CANDLE_CLOSE_ABOVE` (default): a completed 5m candle closes at or above the entry after the prior candle closed below it.
* `CROSS_ABOVE`: a buy-stop that fills at the entry, or at the open on a gap up.
* `TOUCH_BELOW`: a buy-limit that requires price to trade **strictly below** the level; a bare touch is not assumed to fill.

Validation: `Entry > Stop > 0`, `Target > Entry`, R:R ≥ 1:2 (warning near the minimum), allocation ≤ available
cash and ≤ the per-trade maximum, and the position, aggregate-risk and quantity checks. A confirmation screen
precedes activation.

Lifecycle: `PENDING_ENTRY` (cash reserved) → `OPEN` only when the trigger fires **and** the MTF conditions pass
→ `CLOSED` at stop or target. Enabling never opens a position by itself. A pending entry expires after
5 trading sessions. *Disable auto entry* pauses a pending trade (`CONFIGURED`, cash released), or stops future
entries for an open position while it keeps being monitored.

## 8. Dashboard 2 — Mechanical Swing scanner

### 8.1 Schedule (Asia/Kolkata, NSE trading days only)
* **Every 5 minutes from 09:15 to 15:00 inclusive** (70 runs per day), active after **Start Auto Scan**.
* **One after-market scan at 19:00**, labelled **AFTER-MARKET SCAN — NOT LIVE MARKET ACTIVITY**. It has
  **its own toggle** and stays on when you press *Stop Auto Scan*, which stops only the 5-minute scans and cancels a running scan.
* **Run Scan Now** runs a manual scan at any time. Only one scan runs at a time.
* Weekends and the holidays in `data/nse_holidays.json` are skipped. Scans run only while the backend runs.

A scan ends as `SUCCESS` (every stock evaluated), `PARTIAL` (some data errors or unmapped stocks), `FAILED`
or `CANCELLED`. A scan is never reported as successful just because it started.

### 8.2 Rules (`app/strategies/dashboard2_mechanical.py`)
Timeframes: **Daily** for trend, **4H** for impulse, structure, Fibonacci and demand zones, **1H** for the pullback and confirmation.

| Rule | Mandatory test |
|---|---|
| A | Daily close > Daily EMA50 (a rising EMA adds score) |
| B | Latest confirmed 4H swing high H, preceded by swing low L; a close above the prior swing high between L and H (BOS); `H−L ≥ 2×ATR14(4H)`; no higher high since H; no 4H close below L |
| C | ≥ 3 consecutive completed 1H candles with `close < open` after H |
| D | Pullback low **strictly below** `H − 0.5(H−L)` and above L. 61.8% and 78.6% are reported and scored |
| E | Look-left demand zone: a base of 1–3 small-bodied 4H candles, followed by a displacement candle (body ≥ 1.2×ATR) and a structural break within 10 bars, not violated since. The pullback must reach it without a 1H close below it. Zone = [base low, base body-top] |
| F | First completed bullish 1H candle (`close > open`) after the red run, at or after the discount touch, ≤ 6 bars old |
| G | Daily, 4H and 1H data present and FRESH |
| H | Entry = confirmation high + 1 tick (buy-stop); Stop = min(pullback low, zone low) − max(0.1×ATR4H, tick); Target = Entry + 3×(Entry−Stop); RR ≥ 3; Target ≤ L + 1.618(H−L) (no forced unrealistic targets); risk ≤ 8% of entry; not already triggered before detection |

**Score (0–100):** trend/structure 20, impulse/BOS 15, pullback 15, Fibonacci 15, demand zone 15,
confirmation 10, liquidity/feasibility 10. Grades: **A+ ≥ 85, A 75–84**; below 75 is not a qualified
recommendation. Any mandatory failure means REJECTED regardless of score. Every component and rejection
reason is stored and shown when you expand a row. The score is not a probability of profit.

**Signals:** one row per setup (keyed on symbol, impulse high and confirmation candle), so repeated scans
update the same row instead of adding duplicates. A signal is valid until the close of the next trading
session. It is `INVALIDATED` if a later scan breaks the setup, and `EXPIRED` afterwards.

### 8.3 Paper auto trade
The strategy's entry, stop and target are shown read-only. You enter and confirm an allocation. Optional
overrides are labelled `OVERRIDDEN`, keep the original values, and must still meet 1:3. Entry is simulated
only if a completed 5m candle crosses the buy-stop while the signal is still valid. Trading at or below the
stop first invalidates it, and a gap above the entry beyond the deviation limit rejects the fill (not chased).
Each signal can be traded only once.

## 9. Paper-trading engine

* **States:** `CONFIGURED` (paused), `PENDING_ENTRY`, `OPEN`, `CLOSED`, `CANCELLED`, `REJECTED`, `EXPIRED`. Partial fills are not simulated, so there is no `PARTIALLY_FILLED` state.
* **Sizing:** `per-share risk = entry − stop`; `risk budget = min(available × risk%, max risk/trade, your max risk)`; `qty = min(floor(allocation/entry), floor(budget/risk))`, rounded to the lot size. Your allocation is never increased.
* **Defaults (per account):** risk 1%/trade, max ₹2,000 risk/trade, max ₹50,000 allocation/trade, 5 simultaneous positions or pending entries, aggregate planned risk ≤ 5% of capital, slippage 5 bps, max entry deviation 0.5%.
* **Cash:** arming reserves the allocation. A fill converts it to a position (quantity is trimmed so cost plus charges ≤ allocation). Cancel or expiry releases it. D1 and D2 cash are fully separate.
* **Fills:** simulated on completed Dhan 5m candles. Gaps fill at the open. If stop and target are both inside one candle, the stop is assumed first (no invented intrabar path). An intrabar entry whose candle also reaches the stop exits at the stop.
* **Costs:** estimated delivery charges (STT 0.1% each side, NSE txn, SEBI, stamp 0.015% on buy, ₹12.5 DP + GST on sell, ₹0 brokerage) and slippage. These are estimates only.
* **Integrity:** every cash or position change happens in one transaction under a lock. `UNIQUE(trade_id, side)` on executions and `UNIQUE(account, idempotency_key)` on trades prevent duplicates. Each 5m candle is processed once per trade, including after a restart.
* **Paper Trade Book:** views for pending, open, closed, rejected and cancelled/expired trades, filters by strategy, symbol and date, a detail view with simulated executions and the event timeline, cancel / disable / re-enable, and **manual paper exit** at the latest fresh quote (paper ledger only).
* **Trade History:** closed trades per strategy, simulated net P&L, win/loss counts, average win/loss, profit factor and a cumulative P&L chart. These are paper results, not evidence of real profitability.

## 10. TradingView charts

Each modal has a chart panel with two supported integrations (nothing is scraped):
1. **Dhan data · engine view.** TradingView's open-source **Lightweight Charts** library renders the same
   validated, completed Dhan candles the engines use (5m/15m/1H/4H/1D). Entry, stop, target, Fibonacci and
   demand-zone levels are drawn as price lines.
2. **TradingView widget.** The official Advanced Chart embed (`NSE:SYMBOL`; `&` and `-` become `_`, e.g. `NSE:M_M`).
   It uses TradingView's own feed, is display-only, and may show "symbol unavailable" for some NSE symbols
   because of exchange licensing in embeds.

A **price-levels panel** beside the chart always lists the plan levels. If Dhan data is unavailable, the
chart shows the actual error and no placeholder chart. No configuration is needed; the widget needs internet
access to `s3.tradingview.com`.

## 11. OpenAI explanations

Optional. In Settings, save a key (encrypted, masked), choose a model and toggle **Enable AI explanations**.
**Test OpenAI Connection** lists the models available to your key and loads them into the dropdown. Until then
a fallback list is shown, which may not match your account. The status shows `CONNECTED`, `AUTH_FAILED`,
`QUOTA_EXCEEDED`, `RATE_LIMITED`, `MODEL_NOT_FOUND` or `NETWORK_ERROR`, plus the last success time.

*Explain with AI* in the Dashboard 2 modal sends the stored engine output to the Responses API with
instructions to use only those facts. The answer is shown in a separate box. Any number in it that does not
appear in the engine data is flagged as unverified. The AI has no tools and cannot change signals, risk,
allocations or trades. Everything works with AI disabled.

## 12. Tests

```bash
cd backend && source .venv/bin/activate && python -m pytest -q     # 143 tests
cd frontend && npm test                                              # 6 tests
cd frontend && npx tsc --noEmit -p . && npm run build                # type check + build
```

All external calls (Dhan, OpenAI, NSE downloads) are mocked. Synthetic candles live only in
`backend/tests/synthetic.py`, are labelled as such, and are never used at runtime. Coverage includes EMA,
ATR and pivots, every D1 timeframe rule, missing and stale data, each Mechanical Swing rule A–H, scoring and
grades, signal de-duplication and invalidation, sizing and validation, cash reservation and release, fills,
gaps, conservative same-candle exits, idempotency, persistence across restart, independent ledgers, the
scheduler (70 slots 09:15–15:00, 19:00 job, holidays, no duplicate jobs, shutdown), concurrent and cancelled
scans, credential encryption, masking and log redaction, Dhan error classification and retries, API flows,
and the paper-only safeguards in §19.

## 13. Database backup and reset

```bash
python scripts/db_tools.py backup        # online-safe copy to data/backups/
python scripts/db_tools.py reset --yes   # stop the backend first; backs up, then deletes data/trading.db
```

Keep `data/.secret.key` with your backups: saved credentials in a backup can only be decrypted with it.
For PostgreSQL, set `PT_DATABASE_URL=postgresql+psycopg://…`, install a driver and start the backend; the
models are portable and migrations use Alembic. This path has not been exercised.

## 14. Security

* Secrets are encrypted at rest with Fernet. The key is in `data/.secret.key` (mode 0600). Anyone who can
  read both the key and the database can decrypt them. This is not an OS keychain.
* The API returns secrets masked, never in full. Logs pass through a redaction filter for tokens and keys.
* `.env`, the database, the key file and the scrip-master cache are git-ignored. `.env.example` has placeholders only.
* The servers bind to `127.0.0.1`. There is **no login**: anyone with local access to the port can use the
  app, so do not expose it to a network.
* Inputs are validated with Pydantic (symbol regex, positive finite numbers, model-name pattern) and queries use the ORM.
* Deleting credentials and resetting accounts require explicit confirmation.

## 15. API costs and limits

* **Dhan:** Data APIs require an active Dhan data subscription (check Dhan's current pricing). The client
  stays below the documented limits (~4 req/s for charts, 1 req/s for quotes, ≤ 1000 instruments per quote
  request) and retries rate-limit and server errors with exponential backoff (0.5 s, 1 s, 2 s). Rough load:
  a Nifty 250 scan makes about 250 chart requests (daily candles are cached for 30 min), so ~1–2 minutes per
  scan. A Nifty 100 MTF refresh makes about 400 requests every 15 minutes. Check that this fits your daily quota.
* **OpenAI:** billed per token by OpenAI. Explanations are on-demand only (one call per click, ≤ 900 output tokens).

## 16. Troubleshooting

| Symptom | Fix |
|---|---|
| Header shows `NETWORK_ERROR` / `ProxyError` | Your network blocks `api.dhan.co`; check firewall or proxy |
| `AUTH_FAILED` | Token expired or wrong; replace it and test again |
| `PERMISSION_DENIED` | Data APIs not enabled on your Dhan account |
| Universe download fails (403) | NSE blocks automated downloads from some networks; download the CSV in a browser and upload it |
| Stocks show `MISSING_IN_SCRIP_MASTER` | Re-sync the scrip master; the symbol may have changed (see the mapping note) |
| Everything `NOT EVALUATED` | Configure Dhan, then *Refresh MTF now* |
| No qualified D2 setups | Normal. All rules A–H must pass. Check *Rejected candidates* for the reasons |
| Scans `PARTIAL` | Some stocks had data errors; the message names the last one |
| Calendar warning | Verify `data/nse_holidays.json` against the NSE circular and set `"verified": true` |
| UI says backend unreachable | Start the backend on 127.0.0.1:8000 |

## 17. Strategy interpretation notes

**The two reference files named in the brief (`Pasted text(20261024-054949).txt` and
`Mechanical_Swing_Trading_System.pdf`) were not present in the repository or the build environment.**
Dashboard 2 therefore implements the rules exactly as written in the project brief (§7.5 A–H, §7.6 scoring).
Every point where the brief leaves room for interpretation is an explicit, documented choice in
`MechParams` (`dashboard2_mechanical.py`), so you can align it with the PDF:

* Timeframe mapping: Daily trend, 4H impulse/structure, **1H** pullback and confirmation.
* Swing points: 2-left/2-right fractal pivots (confirmed only after 2 later bars, so there is no look-ahead).
* "Meaningful impulse": ≥ 2× ATR14(4H).
* Demand-zone algorithm (base + displacement + BOS + not violated; prior reactions and gaps add score).
* Entry = buy-stop 1 tick above the confirmation high. Stop buffer = 0.1× ATR14(4H).
* "Structurally unrealistic" target = beyond the 1.618 extension of the impulse.
* Signal validity = until the close of the next trading session; confirmation must be ≤ 6 1H bars old.
* "Nifty 250" = the official **NIFTY LargeMidcap 250** index (there is no index named exactly "Nifty 250").

Dashboard 1's MTF rules are the documented baseline from the brief (§6.11), because no separate full rule
set was supplied.

## 18. Known limitations

* **Not verified against real APIs.** The build environment had no access to `api.dhan.co`,
  `images.dhan.co`, `niftyindices.com` or OpenAI, and no credentials were available. Endpoint shapes follow the
  official `dhanhq` 2.3.0 SDK source. The first real connection test may reveal format differences (for example
  intraday date formats or quote field names) that need small fixes.
* Quotes are REST snapshots polled every 60 s. Dhan WebSocket streaming is **not implemented**. Fills use completed 5m candles, so entries and exits are decided up to ~5 minutes after the price move.
* The 2026 NSE holiday list was compiled at build time and is marked **unverified** until you confirm it.
* Charges are estimates. No partial fills. Long (BUY) only.
* Monitoring and scans run only while the backend process is running. Missed scans are not back-filled.
* Docker and PostgreSQL paths are provided but were not run in the build environment.
* No authentication (local single-user by design).

## 19. No-live-trading verification

* `backend/app/integrations/dhan_client.py` whitelists six read-only endpoints (`/profile`, `/charts/historical`,
  `/charts/intraday`, `/marketfeed/ltp|ohlc|quote`). Any other path raises `ForbiddenEndpointError` before a request is built.
* The official `dhanhq` SDK, which contains order methods, is not a dependency and is not imported.
* `tests/test_paper_only_safeguards.py` checks this on every run. It scans the source for order-endpoint and
  order-method strings, AST-checks imports, asserts the client has no order-like methods and calls only
  whitelisted paths, asserts every trade and execution row defaults to `simulated=True`, and asserts there is no
  live-trading config field. `tests/test_dhan_client.py` asserts order, kill-switch, eDIS, margin and funds endpoints are refused.
* `PAPER_TRADING_ONLY = True` is a hard-coded constant, not configuration. The header banner and `/api/health` report it.
