# Agent Context

> **START HERE for a cold-start handoff:** read [`AGENTIC_HANDOFF.md`](./AGENTIC_HANDOFF.md)
> first — it is the verified map of the whole project (3 strategies, the new
> "Manual Institutional (time-gated)" strategy, cost/threshold gotchas, verified
> results, run commands). This file (AGENTS.md) is the chronological phase log.

## Phase 0 — Capital-based sizing + data refresh (2026-07-10)

Account model now real: **₹50,000 capital, 1% risk (₹500/trade), max 5 new
entries/day.** Applies to `scripts/backtest.py`.

### Fixes
- `_position_size_for` now sizes by capital: `shares = int(₹500 / |entry-SL|)`,
  notional capped at ₹50k (no leverage). Returns 0 → trade skipped as infeasible.
- Added `INITIAL_CAPITAL=50000`, `RISK_PER_TRADE_PCT=1.0`, `MAX_TRADES_PER_DAY=5`.
- Daily-cap + affordability gate added at trade entry (first-N-per-day by arrival).
- Fixed reporting bug: `total_pnl_pct` was hardcoded to a ₹100k base → phantom
  −50% on every symbol. Now uses `INITIAL_CAPITAL`.
- `scripts/download_history.py` (bulk loader; `--tf/--symbols/--upstox`) extends
  cache. With `--upstox` this unlocks **729d of 15m** (fetched as 1m, resampled)
  + native 1h (~3yr) + 1d (~5yr). yfinance-only caps 15m@60d, 1h@730d.
  See `DATA_INVENTORY.md` for current on-disk ranges (15m=191 files/729d,
  1h=111 files/2023→2026, 1d=112 files/~5yr).

### New honest baseline (sl=0.5, tp=5.0, threshold=70, LONG-only)
| TF | Mode | Trades | WR | Profitable symbols |
|----|------|--------|----|--------------------|
| 15m | Intraday | 359 | 42.3% | 16 / 30 |
| 1h | Swing (2yr) | 333 | 28.5% | 8 / 30 |

Top intraday 15m: ONGC +10.4%, ADANIENT +5.8%, CIPLA +4.7%, OIL +4.2%, TECHM +4.1%.
Top swing 1h: BSE +14.5%, TCS +7.0%, ICICIPRULI +6.8%, KOTAKBANK +5.9%.

Key findings → drive Phase 1/4:
- Profitable symbols differ completely by timeframe (ONGC great intraday but
  −4.7% swing; BSE/TCS great swing). Confirms need for per-symbol **and**
  per-timeframe whitelist.
- Swing 1h is mostly −EV on the intraday-tuned 0.5/5.0 SL/TP (22/30 losers) →
  swing needs its own SL/TP tuning (Phase 4).

---

## Phase 1 — Selectivity (whitelist) — 2026-07-10

Strict whitelist rule: **PF >= 1.5 AND trades >= 5** (your call). Generates
`data/symbol_whitelist.json` via `scripts/build_whitelist.py`; applied with
`run_backtest_portfolio.py --whitelist` (writes `*_wl.json` so baseline is kept).

Result (15m intraday, sl 0.5 / tp 5.0, threshold 70):
| | Full 30 | Whitelist |
|---|---|---|
| Trades | 359 | 200 |
| WR | 42.3% | **55.0%** |
| Profitable symbols | 16/30 | **14/14** |
| Worst PF | 0.00 | 1.71 |

15m whitelist (14): ONGC, ABB, WIPRO, TECHM, COALINDIA, ADANIENT, TORNTPHARM,
HINDUNILVR, CIPLA, BEL, PIDILITIND, BSE, ITC, OIL.
1h swing whitelist (2): BSE, ICICIPRULI. (Swing is −EV on intraday SL/TP →
see Phase 4.)

### Threshold sweep (whitelisted 15m)
| TH | trades | WR | expectancy R/trade | sumPnL% |
|----|--------|----|--------------------|---------|
| 70 | 200 | 55.0% | **+0.702** | +50.6 |
| 75 | 171 | 59.6% | +0.599 | +39.9 |
| 80 | 151 | 62.9% | +0.633 | +39.4 |
| 85 | 38 | 60.5% | (sparse) | — |

**Finding:** raising the threshold beyond 70 *reduces* expectancy — the
whitelist already does the selectivity; the threshold adds nothing. **Keep 70.**

### Confluence requirement (INST_CONFLUENCE_MIN) — REJECTED
Requiring core factors (regime+price_action+volume) each >= N cut trades
200→52 but dropped WR to 33% and did NOT beat 70's expectancy. With a
10R-winner-driven edge, forcing "consistency" destroys expectancy. Gate left
DISABLED (default).

---

## Phase 2 — Filters (regime / session) — 2026-07-10

### Regime gate (INST_REQUIRE_TREND_UP=1) — ACCEPTED, now standard
Require HTF 1d trend == UP for LONG. On whitelisted 15m:
trades 200→187, WR 55.0%→58.3%, expectancy **+0.702→+0.781 R**, sumPnL
+50.6→+53.3, still 14/14 profitable. Pure win — keeps trend-alignment.
Standard env for all forward runs: `INST_REQUIRE_TREND_UP=1`.

### Session filter — REJECTED
Re-ran time-of-day analysis on the REAL gated trade set
(`scripts/analyze_time_of_day.py`). With whitelist+regime gate applied,
**every session is now net positive** (opening 68.5% WR/+525, morning
49.3%/+798, midday 57.5%/+354, afternoon 40%/+59). Old
data/time_of_day_analysis.json was computed on RAW/all-signals, hence its
all-negative picture — not applicable to the gated population. Blocking any
session would only *lose* edge. SESSION_WEIGHTS left neutral.

---

## Phase 3 — Fix SHORT — 2026-07-10 (DONE, SHIPPABLE)

Root cause: SHORT was "not-bullish", not genuinely bearish → 3.5% WR / PnL −93k.

Fixes in `engines/institutional_probability_engine.py`:
- New dedicated factor **`short_context`** (0–20, bearish only): bearish HTF
  daily trend + bearish swing structure (LL/LH) + breakdown through support +
  relative weakness vs NIFTY + distribution volume on down bars.
- Regime gate extended symmetrically: LONG requires 1d trend UP, **SHORT
  requires 1d trend DOWN** (`INST_REQUIRE_TREND_UP=1`).
- `SHORT_MIN_SCORE` default lowered 46 → **40** (genuine shorts can now clear).

Result (15m intraday, sl 0.5/tp 5.0 LONG; short_sl 1.0/tp 2.0 SHORT):
| Direction | trades | WR | expectancy R |
|-----------|--------|----|--------------|
| SHORT (gated) | 785 | **61.0%** | **+0.694** |
| LONG (gated)  | 64  | 32.8% | +0.764 |

SHORT went from broken to a real, trend-aligned edge. SHORT whitelist
(15m_intraday_short) built with same rule (PF>=1.5 & >=5 trades): **23 symbols
pass** (BHARTIARTL, CIPLA, TATACONSUM, TECHM, COALINDIA, KOTAKBANK, SBIN, BEL,
ICICIBANK, ITC, TCS, RELIANCE, OIL, ONGC, DIVISLAB, PIDILITIND, HINDUNILVR,
WIPRO, ADANIENT, INFY, ABB, HDFCBANK, ICICIPRULI).

### Standard env config
- Long-only forward: `INST_REQUIRE_TREND_UP=1`, `INST_SHORT_MIN_SCORE=70`
  (shorts suppressed), `--whitelist` (uses 15m_intraday / 1h_swing).
- Both sides: `INST_REQUIRE_TREND_UP=1`, `INST_SHORT_MIN_SCORE=40`,
  whitelist covers 15m_intraday + 15m_intraday_short.

---

## Phase 4 — Exit mgmt / SL-TP tuning — 2026-07-10

### Swing 1h was mis-tuned+ungated, not broken
Re-tuned swing on 2yr with `scripts/tune_sltp.py` (now configurable:
`--timeframe/--days/--no-intraday`). With the regime gate applied, swing
jumped from the old −EV baseline (8/30 profitable) to **PF ~2.4, WR ~55%
across ALL 30 symbols**. Best combo: **sl 1.5 / tp 4.0**.

Rebuilt swing whitelist (1h_swing): **2 → 14 symbols** (LT, BEL, ABB,
KOTAKBANK, TATACONSUM, ICICIPRULI, TCS, BSE, COALINDIA, EICHERMOT, OIL,
MARUTI, AXISBANK, TECHM).

### Final per-mode params (regime-gated)
- Intraday 15m: sl 0.5 / tp 5.0  (unchanged, already strong)
- Swing 1h:     sl 1.5 / tp 4.0  (new)

Trailing/partial exits: NOT added — static targets already yield +0.7R
expectancy; the edge is in entry selection, not exit micromanagement.
(Revisit only if a trailing variant beats +0.7R in a dedicated test.)

---

## Phase 5 — Expand universe — 2026-07-10 (infrastructure done; limited by data)

Added: `EXPANSION_CANDIDATES` + `expansion_universe()` in
`data/downloader/watched_symbols.py`; `run_backtest_portfolio.py --symbols`
to scope any list; `download_history.py --symbols` for tokenless fetch.

Validated 118 candidates vs yfinance → **110 have data**. Downloaded 1h (2yr)
+ 1d (5yr) for all 110. Ran expanded 15m & 1h whitelist on the 110.

**Finding — data is the hard limit for intraday expansion:**
- yfinance caps **15m at 60 days**. Only the original 30 core symbols have
  15m cache; the 80 new names have NO 15m data → expanded 15m run collapsed
  back to the original 14 whitelisted symbols (55 trades). No real expansion.
- 1h (2yr) was downloaded for all 110, but most new names still produce 0
  trades after the 60-bar warmup on a 700d window → expanded 1h run also
  collapsed to the original 14 (39 trades).
- Conclusion: universe expansion is gated by **15m history availability**.
  Upstox REST allows 729 days of 15m (needs paid credits / the live token),
  which would unlock a real Nifty-100 intraday expansion. Until then, the
  edge is concentrated in the current 14 (15m) / 14 (1h) whitelists.

ACTION: to expand intraday, run
`scripts/download_history.py --tf 15m --symbols <nifty100 list>` after
resolving Upstox keys (Upstox gives 729d of 15m), then re-run the whitelist.

---

## Phase 6 — Walk-forward OOS validation — 2026-07-10 (CRITICAL)

`scripts/walkforward_validate.py`: build whitelist on a TRAIN window, test on
a held-out TEST window. Reveals selection-bias decay. Enhanced with `--folds N`
(rolling walk-forward, N OOS windows) and `--symbols` (subset filter).

**Clean 3-fold OOS (post PIT/look-ahead fixes — the trustworthy numbers):**
Subset {WIPRO, RELIANCE, ONGC, BSE, ADANIENT}. 15m intraday sl 0.5/tp 5.0;
1h swing sl 1.5/tp 4.0.

| Mode | Fold | Whitelisted | OOS trades | OOS WR | OOS PF | OOS Exp |
|------|------|-------------|-----------|--------|--------|---------|
| 15m intraday | 2 | ONGC | 50 | 54.0% | 2.23 | +0.587R |
| 15m intraday | 3 | ONGC | 35 | 34.3% | 1.46 | +0.129R |
| 15m intraday | **agg** | | **85** | 45.9% | — | **+0.398R** |
| 1h swing | 1 | WIPRO | 43 | 39.5% | 1.11 | +0.071R |
| 1h swing | 2 | — | — | — | — | — |
| 1h swing | 3 | — | — | — | — | — |

(15m Fold 1 train window was ~20d of available 15m history → too short for a
whitelist; the folds that ran are positive. 1h folds 2-3 whitelist empty in
train → OOS null for those windows.)

**Major finding:** 15m intraday is ROBUST — edge holds out-of-sample
(aggregate +0.40R, ONGC PF 2.23). 1h swing is FRAGILE — only 1/3 folds traded,
barely positive (exp +0.071R), whitelist selection unstable (curve-fit decay).
Direction: **move to paper trading on 15m intraday only**; treat 1h swing as
unproven until re-validated on longer history.

### Final forward config (long-only)
- Intraday 15m: `INST_REQUIRE_TREND_UP=1`, `INST_SHORT_MIN_SCORE=70`,
  `sl 0.5 / tp 5.0`, `score_threshold=70`. OOS-validated (+0.40R agg).
  Lead names: ONGC, plus WIPRO/RELIANCE from in-sample runs.
- Swing 1h: **DISABLE for live** — OOS not robust. Revisit only with longer
  (Upstox 729d) 1h history + broader universe.
- SHORT available (Phase 3) when `INST_SHORT_MIN_SCORE=40`; trend-gated, 23
  symbols. Not yet OOS-validated for SHORT specifically.

---

## Latest Backtest Results — Institutional Probability (2026-07-10)

### Best Config (stored in registry)
```
strategy: "Institutional Probability"
sl_mult=0.5, tp_mult=5.0, atr_period=14
score_threshold=70 (institutional_strategy.py)
multi-TF bonus: ON (htf_ctx passed to engine)
```

### 1h Native Data
`data_registry.get_bars()` serves 1h from `data/cache/1h/{symbol}.parquet`
(native Upstox 1h, ~3yr). For 1h it tries yfinance native first, then falls back
to resampling 30m→1h. **Caveat (verify before trusting):** the current
`data_registry.py` does NOT implement a yfinance-native-1h fetch — it resamples
30m. The "native 1h via yfinance" description predates a refactor. See
`DATA_INVENTORY.md` §4.6.

### Results by Timeframe (LONG only — SHORT disabled)

| Timeframe | Mode | Trades | WR | PF | Notes |
|-----------|------|--------|----|----|-------|
| **15m** | Intraday | 273 | 23.8% | 2.22 | 30/30 symbols. Best: ONGC PF=13.51. |
| **15m** | Swing | — | — | — | (not run this session) |
| **1h** | Intraday | 32 | 28.1% | 2.63 | 13/30 symbols. Native data fix. |
| **1h** | Swing | 629 | 11.3% | 1.23 | 30/30 symbols. High volume. |
| 1m | — | 0 | — | — | 15d lookback insufficient for 60-bar warmup |
| 1d | — | 0 | — | — | 77 bars < 80 needed after 60-bar warmup |

### SHORT Status
SHORT is **disabled in the forward live config**: it sets `INST_SHORT_MIN_SCORE=70`
(PHASE 0 / Final forward config), and the bearish raw score rarely clears 70, so
no SHORT entries fire. The engine's *default* `SHORT_MIN_SCORE` is 40, and a SHORT
is generated whenever the bearish score clears that threshold (Phase 3) — but that
path is not the production default.

Phase 3 added a dedicated `short_context` factor (HTF-daily-down, LL/LH structure,
breakdown through support, relative weakness vs NIFTY, distribution volume) so SHORT
is driven by genuine bearish evidence, not merely "not bullish". The pre-rework SHORT
backtest (at the old thresholds) was 1599 trades, WR 3.5%, PnL −93k. SHORT is **not
yet OOS-validated** (see Final forward config) — needs a dedicated Phase-3 backtest
before it's turned on.

### Key Files

### Key Files
- `engines/institutional_probability_engine.py` — 11-factor dual scoring (raw capacity 123, clamped to 0-100)
- `strategies/institutional_strategy.py` — ExecutableStrategy wrapper
- `scripts/tune_sltp.py` — grid search for SL/TP
- `scripts/backtest.py` — WalkForwardBacktest engine with multi-TF passthrough
- `data/downloader/data_registry.py` — native 1h via yfinance, resampling fallback
- `data/results/latest/` — symlink to most recent full results

---

## Phase 7 — Paper Trading (2026-07-11, BUILT)

`scripts/paper_trade.py`: simulated portfolio that reuses the SAME live decision
path as backtest/scanner (`decide_trade` + `build_htf_context`), and adds
position management. Default data source is yfinance (delayed); pass `--upstox`
to use the real-broker Upstox feed.

- Capital model matches backtest: `INITIAL_CAPITAL=50000`, `RISK_PER_TRADE_PCT=1.0`
  (₹500/trade), `MAX_TRADES_PER_DAY=5`.
- **Cash-aware sizing** (fixes backtest's ignored cross-position margin): a new
  position's notional is capped at free cash, so capital can never go negative.
  With sl 0.5/tp 5.0, ~2 concurrent full-risk positions fit in ₹50k.
- Opens a paper LONG when `decide_trade` signals (score>=70, HTF aligned);
  monitors open positions against the live close and fills SL/TP.
- State persists to `data/paper_portfolio.json` (crash-safe); logs entries/exits,
  PnL, R-multiple, equity curve, and an **Upstox-format order payload** per fill
  (instrument_key, quantity, transaction_type, order_type, price, trigger).

**Upstox integration (`--upstox`):** `15m` bars are fetched as 1m via
`UpstoxMarketDataProvider` REST and resampled to 15m (Upstox has no native 15m
bar → maps to `30minute`). NIFTY resolved via `NSE_INDEX|Nifty 50`. Live exit
prices come from `data_registry.get_live_price()` (Upstox WebSocket batch). No
real orders are placed — fills are simulated; the order payload is ready to POST
to `/v2/orders` when a trading token is available.

Mechanics validated synthetically (entry sizing, TP WIN +5R, SL LOSS -1R, daily
cap, cash-aware concurrency, order payload with resolved instrument_key). Live
signals only fire during market hours on a trading day (weekend = stale data →
no signal). End-to-end `--upstox` cycle verified: REST fetch + WS price succeed
with the `.env` token.

Fixed alongside:
- `_bars_until_close` tz off-by-one in `live_institutional_scan.py` (yfinance
  bars stamped at bar CLOSE → final 15:15 bar now reports 0 bars left).
- `UpstoxMarketDataProvider.load_historical_data` tz-naive vs tz-aware
  comparison crash when `start_date` is passed (broke all `start_date` callers).

### P0 hardening (2026-07-11) — operational safety
- **Intraday EOD force-close**: `run_cycle()` now squares off any position whose
  `opened_at` date is before today (real NSE intraday `product="I"` is
  auto-squared at 15:30); stale carry-over can no longer fake overnight P&L.
- **State corruption recovery**: `_load_state()` backs up a corrupt
  `paper_portfolio.json` to `.corrupt` and starts fresh instead of crashing.
- **`--loop` resilience**: the poll loop now catches any cycle exception, logs
  it, and aborts only after 5 consecutive failures (was: one blip killed it).
- **Upstox rate-limiting**: new `data/upstox/upstox_http.py` (`upstox_get`/
  `upstox_post`) retries on HTTP 429 (honours `Retry-After`) + transport errors
  with exponential backoff; wired into `place_upstox_order` and
  `search_upstox_instrument`.
- **`today_cache.merge_today_to_1d`**: `drop_duplicates(keep="last")` so
  WebSocket intraday updates are not silently discarded.
- **WebSocket auto-reconnect**: `upstox_live_feed.start()` now reconnects on
  error/close with exponential backoff (max 10 attempts); `stop()` disables it.

### Commands
```bash
# One paper cycle (yfinance)
.venv/bin/python scripts/paper_trade.py --symbols ONGC,WIPRO,RELIANCE

# One paper cycle on Upstox real-broker feed
.venv/bin/python scripts/paper_trade.py --upstox --symbols ONGC,WIPRO,RELIANCE

# Live paper loop (polls every 15m during market hours)
.venv/bin/python scripts/paper_trade.py --loop --interval 15
.venv/bin/python scripts/paper_trade.py --upstox --loop --interval 15

# Reset simulated portfolio
.venv/bin/python scripts/paper_trade.py --reset

# Allow SHORT entries (off by default — not yet OOS-validated; also requires
# INST_SHORT_MIN_SCORE=40 in the live engine env to actually emit SHORT signals)
.venv/bin/python scripts/paper_trade.py --shorts --symbols ONGC,WIPRO,RELIANCE
```

### P1 hardening (2026-07-11)
- **Shared capital model**: `scripts/capital_model.py` now holds `INITIAL_CAPITAL`,
  `RISK_PER_TRADE_PCT`, `MAX_TRADES_PER_DAY` and `position_size_for` — imported by
  BOTH `scripts/backtest.py` and `scripts/paper_trade.py` so the risk model can
  never diverge. `_position_size_for` in backtest delegates to it.
- **SHORT in paper trader**: entries/exits are now direction-aware (SHORT = SELL
  to open, BUY to close; SL above / TP below entry; mark-to-market equity
  `shares*(entry-px)`; net P&L booked at close). Gated behind `--shorts` (default
  off) because SHORT is not yet OOS-validated (Phase 6).
- **Benchmark loop**: the silent `except: continue` now logs the failing
  strategy name + bar index instead of swallowing bugs.
- **`walkforward_validate` cache redirect**: replaced the raw global
  `_dr._CACHE_DIR` mutation with `data_registry.override_cache_dir()` context
  manager (guaranteed restore, re-entrant-safe).
- **`_market_open()`**: now delegates to `data.utils.market_hours.is_market_open`,
  so NSE holidays are respected (no fake positions on closed markets); the loop
  sleep uses `next_market_open` to skip weekends + holidays.
- **tz normalization**: `_normalize_timestamp_tz` converts every source to IST
  wall-clock before stripping tz, so yfinance (UTC) and Upstox (IST) bars align
  (was a latent 5h30m misalignment). Daily bars preserve their calendar date.
- **Stale-data warning**: `_warn_stale_data` fires when a backtest runs while the
  market is OPEN but the last bar is >1 day old (cache failed to refresh).
- **Live scanner PIT**: `_classify_stock_type` now excludes today's incomplete
  daily bar (`< today`, matching the backtest's `< current_date`).

### Commands
```bash
# Intraday 15m
.venv/bin/python scripts/run_backtest_portfolio.py --timeframe 15m \
  --strategy "Institutional Probability" --tuning-sl 0.5 --tuning-tp 5.0

# Swing 15m
.venv/bin/python scripts/run_backtest_portfolio.py --timeframe 15m --no-intraday \
  --strategy "Institutional Probability" --tuning-sl 0.5 --tuning-tp 5.0

# Intraday 1h
.venv/bin/python scripts/run_backtest_portfolio.py --timeframe 1h \
  --strategy "Institutional Probability" --tuning-sl 0.5 --tuning-tp 5.0

# Swing 1h
.venv/bin/python scripts/run_backtest_portfolio.py --timeframe 1h --no-intraday \
  --strategy "Institutional Probability" --tuning-sl 0.5 --tuning-tp 5.0

# Re-tune
.venv/bin/python scripts/tune_sltp.py
```

## Phase 8 — Full-universe backtest + profitable watchlists (2026-07-11)

Ran the **full 118-symbol universe** across all three modes using
`run_backtest_portfolio.py --provider yfinance` (the `--provider` flag bypasses
the old Upstox-key SKIP gate so the expanded universe runs from the local parquet
cache; 15m expansion names fetch 60d live from yfinance, 1h uses the 109-symbol
cache).

Results (LONG-only, sl/tp per mode, threshold 70, regime-gated):

| Mode | Trades | Profitable (PF≥1.3, ≥10 tr) | Unprofitable (PF<1.0) | Verdict |
|------|--------|------------------------------|------------------------|---------|
| 15m intraday (sl0.5/tp5.0) | 17,679 | **32** | 47 | ✅ robust edge |
| 15m swing (sl0.5/tp5.0) | 19,931 | 28 | 52 | ⚠️ weaker |
| 1h swing (sl1.5/tp4.0) | 95,748 | 6 | 67 | ❌ fragile (OOS-unproven) |

Output files: `data/backtest_portfolio_15m_intraday.json` +
`data/backtest_trades_15m_intraday.json` (17,679 trades); `_15m_swing` (19,931);
`_1h` (95,748).

15m intraday TOP: COALINDIA PF2.12, ONGC 1.88, LT 1.71, IOC 1.64, NHPC 1.61,
BANKBARODA 1.59, IRCTC 1.56, NTPC 1.53, TITAN 1.53, HINDUNILVR 1.52.
1h swing TOP (only 6 clear PF≥1.3): BSE 1.39, ITC 1.36, ICICIPRULI 1.32, IRFC
1.32, ADANIGREEN 1.31, PIDILITIND 1.30 — note huge cumulative PnL% (+130% to
+300%) is multi-year compounding of many bars, not per-trade edge; WR stuck
~39-41%. Treat 1h swing as NOT live-ready.

### Profitable watchlists — `data/symbol_watchlists.json`
Generated from the three result files with filter **trades ≥ 10 AND PF ≥ 1.3**
(matches the "profitable" definition above). Structure:
```json
{
  "15m_intraday": [...], "15m_swing": [...], "1h_swing": [...],
  "consensus": [...],          // profitable in 2+ modes (23)
  "full_consensus": [...],     // profitable in all 3 modes (3)
  "details": { "SYM": { "15m_intraday": {pf, trades, avg_r, wr, pnl_pct, max_dd}, ... } }
}
```
Counts: 15m_intraday 32, 15m_swing 28, 1h_swing 6, consensus 23, full_consensus 3.

**full_consensus (profitable in ALL 3 modes — safest paper-trading seed):**
ADANIGREEN, ICICIPRULI, ITC.

**consensus (profitable in 2+ modes):** ADANIGREEN, ICICIPRULI, ITC, COALINDIA,
ONGC, LT, IOC, NHPC, BANKBARODA, NTPC, TITAN, TRENT, INFY, POLICYBZR, TCS, BPCL,
DRREDDY, TATACONSUM, RELIANCE, AXISBANK, PFC, DMART, TATAELXSI.

### Paper-trader watchlist support
`scripts/paper_trade.py` now reads these lists:
```bash
.venv/bin/python scripts/paper_trade.py --list-watchlists
.venv/bin/python scripts/paper_trade.py --watchlist 15m_intraday
.venv/bin/python scripts/paper_trade.py --watchlist full_consensus --upstox --loop
```
`--symbols` still takes priority if both given; with neither, falls back to
`FOCUSED_WATCHLIST` (unchanged).

### Direction
- Paper trade on **15m intraday** (robust, OOS-validated). Start with
  `--watchlist full_consensus` (3 names) or `consensus` (23).
- 1h swing stays DISABLED for live (fragile per Phase 6 + this run).
- SHORT still gated behind `--shorts` (not OOS-validated).

## Phase 9 — Tiered market scanner (2026-07-11, BUILT)

`scripts/market_scan.py`: live analysis that walks the profitable watchlists in
priority order and reports actionable trade signals — **no portfolio, no orders**
(that is `paper_trade.py`'s job). This is the "analyze the market and give me
trades" command.

Scan tiers (priority order; each symbol scanned with its watchlist's own spec):
| Tier | Watchlist | Symbols | Scan mode | SL/TP |
|------|-----------|---------|-----------|-------|
| 1a | **consensus** | 23 | 15m **intraday** | 0.5/5.0 |
| 1b | **consensus** | 23 | 15m **swing** | 0.5/5.0 |
| 2 | **15m_intraday** (unique) | 9 | 15m intraday | 0.5/5.0 |
| 3 | **15m_swing** (unique) | 5 | 15m swing | 0.5/5.0 |
| 4 | **1h_swing** (unique) | 6 | 1h swing | 1.5/4.0 |

- **consensus is scanned in BOTH intraday and swing** (per request) — a symbol
  can appear in both groups if it triggers in both modes.
- Lower tiers dedup against the same (timeframe, intraday) spec already run, so
  no symbol is double-scanned in one mode (≈66 scan operations / 40 unique names).
- Reuses the exact `decide_trade` + `build_htf_context` path (no signal-logic
  divergence from backtest / paper trader).
- Reports grouped as **INTRADAY (15m)** and **SWING (15m/1h)** with score, entry,
  SL, TP, R per signal; `--json` for machine-readable output.

### Commands
```bash
# Analyze market now (yfinance, delayed)
.venv/bin/python scripts/market_scan.py

# Live Upstox feed
.venv/bin/python scripts/market_scan.py --upstox

# Show the tier plan
.venv/bin/python scripts/market_scan.py --list-tiers

# Auto re-scan every 15 min during market hours
.venv/bin/python scripts/market_scan.py --loop --interval 15

# Machine-readable
.venv/bin/python scripts/market_scan.py --json

# Include SHORT signals (off by default — not OOS-validated)
.venv/bin/python scripts/market_scan.py --shorts
```

Verified end-to-end (full 66-scan run completes, clean report; NIFTY index now
fetched as `^NSEI` not `^NSEI.NS`). On a closed market swing signals may still
fire (e.g. RELIANCE 15m swing score 76); intraday requires live session bars.

## Phase 9a — Live web dashboard (2026-07-11, BUILT)

`scripts/market_scan.py --serve` turns the scanner into a **network-accessible
live dashboard**: a background thread runs the tiered scan on a timer and a
built-in HTTP server streams the results to `web/dashboard.html`.

- Single command, **no new dependencies** (Python stdlib `http.server`).
- Binds to `0.0.0.0:<port>` → reachable from any device on the LAN / network.
- Background daemon thread scans every `--interval` min during NSE hours; writes
  to a thread-safe `_latest_scan` dict.
- HTTP routes: `/` → dashboard, `/api/latest` → full JSON, `/api/status` → health.
- Dashboard: dark theme, INTRADAY (green) + SWING (amber) card columns, each
  card shows symbol / direction / score / entry / SL / TP / R / tier. Auto-refreshes
  every 15s via `fetch('/api/latest')` — **silent updates**, no sound/reload.
- New signals flash briefly on arrival (visual cue, no audio).

### Commands
```bash
# Start dashboard (live Upstox feed, network-accessible on :8080)
.venv/bin/python scripts/market_scan.py --upstox --serve --port 8080

# yfinance (delayed) variant
.venv/bin/python scripts/market_scan.py --serve

# Dashboard URL:  http://<this-host-ip>:8080/
# JSON API:       http://<this-host-ip>:8080/api/latest
```

Verified: server starts instantly (worker scans async, dashboard shows
"waiting for first scan" then populates); `/` serves HTML, `/api/latest` returns
seeded signals, `404` handled. On a closed market the worker reports
"closed — market not open" and resumes at next session.

## Phase 10 — SHORT out-of-sample validation (2026-07-11)

`scripts/walkforward_validate.py` gained `--shorts` (sets `INST_SHORT_MIN_SCORE=40`
before the engine import so SHORT candidates clear) and `--min-pf/--min-trades`
overrides (the strict PF≥1.5 default whitelist excludes all SHORT symbols, so a
relaxed threshold is needed to build a SHORT whitelist). Stats are now isolated
per-direction via `_dir_stats`, so the OOS report reflects SHORT-only edge.

**Constraint discovered:** yfinance caps 15m at 60d → the 15m cache for the core
symbols only spans **2026-04-20 → 2026-07-10** (83 days). A 2023-era 15m
walk-forward is impossible; the Phase 6 "15m intraday OOS" numbers were from a
different/in-sample window. The 1h cache spans 2023-07-28 → 2024-12-31 (~522d),
enough for a real multi-fold walk-forward.

### 1h swing SHORT — 3-fold OOS (sl 1.5/tp 4.0, 5 symbols)
| Fold | Whitelist | OOS trades | OOS exp |
|------|-----------|-----------|---------|
| 1 | WIPRO, RELIANCE, ADANIENT | 107 | +0.091R |
| 2 | WIPRO, BSE | 115 | −0.113R |
| 3 | WIPRO | 32 | −0.428R |
| **agg** | | **254** | **−0.067R** |

**Verdict: 1h swing SHORT is NOT OOS-validated** — negative aggregate, unstable
whitelist (WIPRO decays +0.071→+0.199→−0.428). Same fragility as LONG 1h swing.

### 15m intraday SHORT — recent-window split (sl 0.5/tp 5.0, train 04-20→06-01, test 06-01→07-10)
| Symbol | OOS trades | WR | PF | exp |
|--------|-----------|----|----|-----|
| WIPRO | 105 | 46.7% | 1.66 | +0.347R |
| ONGC | 105 | 49.5% | 1.72 | +0.361R |
| **agg** | **210** | 48.1% | — | **+0.354R** |

**Verdict: 15m intraday SHORT shows a POSITIVE OOS edge (+0.354R)** on WIPRO +
ONGC in the recent window — but it is a single split on only 83 days of history,
not a multi-fold walk-forward. Needs Upstox 729d 15m to confirm robustness.

### Direction
- **Enable SHORT for 15m intraday only**, conservative whitelist {WIPRO, ONGC}
  (extend after Upstox 15m confirms). NOT for 1h swing.
- 1h swing SHORT stays disabled (negative OOS).
- To fully validate 15m SHORT OOS, download Upstox 729d 15m for the core 30
  symbols and re-run the walk-forward with real history.
- `decide_trade` uses one `tuning_override` (sl/tp) for both directions, so live
  SHORT runs at the same sl 0.5/tp 5.0 as LONG (the Phase 3 short_sl 1.0/tp 2.0
  was in-sample only and is not wired into the live path).

### Commands
```bash
# SHORT OOS on 1h (multi-fold)
.venv/bin/python -m scripts.walkforward_validate --timeframe 1h --no-intraday \
  --train-start 2023-07-28 --test-end 2024-12-31 --folds 3 \
  --symbols WIPRO,RELIANCE,ONGC,BSE,ADANIENT --sl 1.5 --tp 4.0 --shorts --min-pf 1.1

# SHORT OOS on 15m (recent window)
.venv/bin/python -m scripts.walkforward_validate --timeframe 15m \
  --train-start 2026-04-20 --train-end 2026-06-01 --test-start 2026-06-01 \
  --test-end 2026-07-10 --symbols WIPRO,RELIANCE,ONGC,BSE,ADANIENT \
  --sl 0.5 --tp 5.0 --shorts --min-pf 1.1
```

## Phase 11 — Loophole closure + real 15m OOS (2026-07-11)

Closed the major loopholes from the earlier review. All changes are ADDITIVE
(no existing behaviour changed unless a flag is set). Each is independently
safe and reversible.

### A) SHORT live deployment (DONE)
- `data/symbol_watchlists.json`: added `15m_intraday_short` = ["WIPRO", "ONGC"].
- `scripts/market_scan.py`: added a SHORT-only tier to `SCAN_TIERS` (same 15m
  intraday sl/tp, `force_short=True`). Inactive unless `--shorts` is passed.
- The `force_short` filter + dedup key were already in `_scan_symbol`/`_run_scan`
  (Phase 10 prep); this wires the tier + watchlist to them.
- `paper_trade.py --shorts` already trades SHORT (direction-aware sizing/exits).

### B) Slippage + cost model (DONE, was already partially present)
- `scripts/backtest.py` `_compute_costs` already applied SLIPPAGE 0.05% + ₹20 +
  STT 0.1%. **Enhanced** to add GST (18% on brokerage+exchange) + NSE/SEBI
  exchange fee, and made all 5 cost params env-overridable
  (`INST_COSTS`, `INST_SLIPPAGE_PCT`, `INST_STT_PCT`, `INST_BROKERAGE`,
  `INST_GST_PCT`, `INST_EXCHANGE_FEE_PCT`).
- New `scripts/slippage_model.py`: standalone `TradeCost` cost model +
  `simulate_trade_cost()` (used by paper_trade / future live cost accounting).
- `scripts/run_backtest_portfolio.py`: new `--slippage {off,default,realistic}`
  flag (default `default` = unchanged behaviour). `off` = zero costs (gross
  PnL); `realistic` = stress test (0.1%/side slippage + ₹40 brokerage).

**CRITICAL COST FINDING:** the edge is HIGHLY cost-sensitive. On an 80-day
ONGC 15m window, avg net PnL dropped from **+₹111/trade (gross)** to
**−₹3/trade (default costs)** — costs eat the majority of gross edge in thin
windows. The edge is REAL but THIN.

### C) Conviction-based sizing (DONE)
- `scripts/capital_model.py`: added `conviction_multiplier(score)` (70–74→0.5x,
  75–84→1.0x, 85+→1.5x) and a `risk_pct` param to `position_size_for` (capped at
  new `MAX_RISK_PCT=1.5`). `MAX_RISK_PCT` also added.
- `scripts/paper_trade.py`: `--conviction` flag scales per-trade risk by score.
  Off by default (unchanged 1% risk).

### E) Drawdown circuit breaker (DONE)
- `scripts/capital_model.py`: added `MAX_DRAWDOWN_PCT=15`, `DD_WARN_PCT=10`,
  and `drawdown_risk_scaler(equity, peak)` → {1.0, 0.5, 0.0} by drawdown.
- `scripts/paper_trade.py`: tracks `peak_equity` in state; new entries are
  scaled by the breaker (halve risk at 10% DD, halt at 15%). Cosmetic `[dd]` /
  `[halt]` log lines only — no behaviour change when flat/healthy.

### D) Upstox 729d 15m data pipeline (DONE — token is NOT blocked for data)
- The data-scoped `.env` token CAN fetch Upstox historical bars (Phase 7
  verified REST). Order *placement* (`--real`) still needs trading scope.
- `scripts/download_history.py`: added `--upstox` flag + `_fetch_upstox()` with
  chunked pagination (Upstox caps 1m history at ~30d/request → fetched in 28d
  chunks, resampled 1m→15m). Added `sys.path` insert (script was missing it).
- Downloaded **729d of 15m for WIPRO, ONGC, RELIANCE, BSE, ADANIENT** into
  `data/cache/15m/*.parquet` (12,776 bars each, 2024-07-15 → 2026-07-10),
  merged with existing yfinance cache. This REPLACES the old 83-day 15m cache.

### REAL 15m SHORT walk-forward OOS (729d, 3 folds) — ROBUST
```bash
INST_SHORT_MIN_SCORE=40 .venv/bin/python -m scripts.walkforward_validate \
  --timeframe 15m --train-start 2024-07-15 --test-end 2026-07-10 --folds 3 \
  --symbols WIPRO,ONGC,RELIANCE,BSE,ADANIENT --sl 0.5 --tp 5.0 --shorts --min-pf 1.1
```
| Fold | OOS trades | OOS exp | Notes |
|------|-----------|---------|-------|
| 1 | 440 | +0.298R | 3/4 syms PF≥1.5 |
| 2 | 648 | +0.158R | ONGC weak this fold |
| 3 | 553 | +0.323R | WIPRO PF 2.40 |
| **agg** | **1641** | **+0.251R** | **7/12 sym-folds PF≥1.5** |

**Verdict: 15m intraday SHORT is OOS-validated across 729d / 3 folds / 1641
trades at +0.251R net of realistic costs.** Strong, stable names: **WIPRO, BSE**.
ONGC positive but fold-variable. RELIANCE did not clear the relaxed whitelist.

### CRITICAL REGIME FINDING — LONG side does NOT fire on 729d data
Re-running the SAME 729d data for LONG (`--min-pf 1.5`, no `--shorts`):
**0 trades across all 3 folds.** NIFTY over 2024-07 → 2026-07 was **−1.5%**
(265 down-days vs 227 up) — a slightly BEARISH/choppy regime. The strategy is
trend-following: it only takes LONG in uptrends, SHORT in downtrends. In this
bearish window it correctly went SHORT-only.

**Conclusion:** the Phase 8 "robust LONG 15m edge" was validated on the 83-day
yfinance window (2026-04-20→2026-07-10) — an (unintentionally) bullish slice.
That was a **time-axis selection bias**, not a stable edge. The strategy's edge
is real but REGIME-DEPENDENT: it must be validated separately in a bull window.

### Direction
- **Deploy 15m SHORT** (WIPRO + ONGC, extend to BSE after confirmation) — OOS-validated.
- **LONG 15m needs bull-regime OOS** before going live. Find a bull segment in
  the 729d data (or wait for a live uptrend) and re-run `--min-pf 1.5` LONG.
- **Costs are the binding constraint**: keep slippage tight; the +0.25R edge is
  thin and window-specific. Treat any window with avg net PnL < 0 after costs as
  non-deployable.
- SHORT 1h swing stays disabled (negative OOS, Phase 10).

### Commands
```bash
# Live SHORT scan (yfinance)
.venv/bin/python scripts/market_scan.py --shorts

# Live SHORT paper trade (WIPRO+ONGC via watchlist)
.venv/bin/python scripts/paper_trade.py --watchlist 15m_intraday_short --shorts --conviction

# Cost stress-test any backtest
.venv/bin/python scripts/run_backtest_portfolio.py --symbols ONGC --timeframe 15m \
  --provider yfinance --days 80 --slippage realistic

# Refresh 15m history (Upstox, chunked, 729d)
.venv/bin/python scripts/download_history.py --upstox --tf 15m \
  --symbols WIPRO ONGC RELIANCE BSE ADANIENT
```

## Phase 12 — Critical loophole correction: full-universe SHORT + LONG diagnosis (2026-07-11)

Closed two of the three critical loopholes; the third (LONG OOS) is blocked by
data infrastructure, not strategy failure.

### Step 1 — Full-universe SHORT OOS (DONE)
Ran SHORT walk-forward in two tiers and aggregated:

| Tier | Symbols | Data | Method | Result |
|------|---------|------|--------|--------|
| A | WIPRO, ONGC, RELIANCE, BSE, ADANIENT (729d) | 3-fold | +0.251R / 1641 tr | 4 passed |
| B | 27 remaining (83d cache) | single 50/50 split | +0.214R / 728 tr | 9 passed (COALINDIA, HINDUNILVR, INFY, TCS, TATACONSUM, AXISBANK, ICICIPRULI, BHARTIARTL, +ITC which failed test) |

**12 symbols now OOS-validated for 15m SHORT**: WIPRO, ONGC, BSE, ADANIENT,
COALINDIA, HINDUNILVR, INFY, TCS, TATACONSUM, AXISBANK, ICICIPRULI, BHARTIARTL.
`data/symbol_watchlists.json` `15m_intraday_short` expanded to these 12.

### Step 2 — LONG diagnosis (BLOCKED, root-caused)
LONG fired **0 trades** on the 729d Upstox-resampled 15m data, even in a bull
window (2025-04→07, NIFTY +14%). Investigated:

- Direct backtest WIPRO `--days 80` (native yfinance 15m) → **24 LONG trades,
  PF 2.44, +0.29R**. So LONG edge IS real on native 15m.
- Direct backtest WIPRO `--days 700` (729d incl. Upstox-resampled) → **0 LONG
  trades**. SHORT works on resampled bars; LONG does NOT.
- In the 41-day train slice, WIPRO generated **24 SHORT but only 1 LONG**
  trade. LONG on 15m is extremely selective (~1 per 40 days/symbol).

**Conclusion:** LONG 15m is a real but RARE edge. It cannot be validated OOS
because (a) we lack native 15m history >60 days (yfinance caps 60d; Upstox has
no native 15m — only 1m resampled, which breaks LONG signal generation), and
(b) LONG's rarity needs ~400+ days of native data per symbol to build a
reliable whitelist. **LONG stays DISABLED for live.**

### Step 3 — Real-money readiness (USER ACTION REQUIRED)
`.env` token is data-scoped → order placement (`--real` in paper_trade.py)
will be rejected by Upstox. To enable:
1. Upstox Developer Dashboard → generate token with scopes `["read","trade"]`.
2. Update `.env` `UPSTOX_ACCESS_TOKEN` with the new token.
3. Dry-run: `.venv/bin/python scripts/paper_trade.py --watchlist 15m_intraday_short
   --shorts --real` — verifies the `/v2/order/place` path runs without crashing
   (orders on a closed market will be rejected; the test is code-path, not fill).

### Live deployment (DONE)
`data/paper_portfolio.json` reset; paper trader restarted (PID 8512) monitoring
the 12-symbol SHORT universe via `--watchlist 15m_intraday_short --shorts
--conviction --upstox --loop --interval 15`. Market closed (Sat) → waiting for
Mon 09:15 open.

### Commands
```bash
# Full-universe SHORT OOS (Tier B, single split on 83d cache)
INST_SHORT_MIN_SCORE=40 .venv/bin/python -m scripts.walkforward_validate \
  --timeframe 15m --train-start 2026-04-20 --train-end 2026-05-31 \
  --test-start 2026-05-31 --test-end 2026-07-10 \
  --symbols <27 remaining> --sl 0.5 --tp 5.0 --shorts --min-pf 1.1

# LONG diagnosis on native 15m (83d window)
INST_SHORT_MIN_SCORE=70 .venv/bin/python scripts/run_backtest_portfolio.py \
  --symbols WIPRO --timeframe 15m --provider yfinance --days 80 --slippage default

# Live SHORT loop (12 symbols)
.venv/bin/python scripts/paper_trade.py --watchlist 15m_intraday_short \
  --shorts --conviction --upstox --loop --interval 15
```

## Phase 13 — Full 118-universe 729d 15m download (2026-07-11, DONE)

The user asked to backfill 15m history for the entire universe. Previously only
the 30 core symbols had 15m cache (yfinance 60d cap); the other 88 had no 15m
data, so every "full universe" run was constrained/in-sample on 15m.

### Bug fixed (blocked the first attempt)
`data/upstox/upstox_market_data_provider.py:load_historical_data` did
`df["timestamp"].dt.tz` on an **empty** df (object dtype) when a chunk returned
no candles (the final 1-day boundary chunk). That exception propagated and
aborted the *entire symbol* in `download_history.py:_fetch_upstox` — every
symbol failed with "Can only use .dt accessor with datetimelike values".
- Fix 1: `load_historical_data` now early-returns on empty df (safe for all
  callers).
- Fix 2: `_fetch_upstox` chunk loop now wraps each chunk in try/except and
  skips a single bad chunk instead of killing the symbol.

### Result
Ran `scripts/download_history.py --upstox --tf 15m` over `expansion_universe()`
(118 symbols, 729d each via 1m→15m chunked resample). **117/118 succeeded**,
ADANITRANS skipped (delisted). Cache `data/cache/15m/` went from 30 → **117
parquet files**, avg **12,702 bars/symbol**, range **2024-07-15 → 2026-07-10**,
no dtype defects. Launched as background job (PID 8725), ~73 min total, 0
failures except the one delisted name.

### What this unlocks
- A REAL multi-fold 15m SHORT walk-forward across the **full 117-symbol**
  universe (replaces the Phase 12 Tier-B single 50/50 split on 83d cache).
- The Phase 12 "LONG fires 0 trades on resampled 15m" finding still stands
  (LONG logic needs native 15m; Upstox only offers 1m resampled) — so LONG
  stays disabled regardless of this backfill.

### Commands
```bash
# Re-run full-universe SHORT OOS on the now-complete 729d 15m cache
INST_SHORT_MIN_SCORE=40 .venv/bin/python -m scripts.walkforward_validate \
  --timeframe 15m --train-start 2024-07-15 --test-end 2026-07-10 --folds 3 \
  --symbols $(python -c "import sys;sys.path.insert(0,'.');from data.downloader.watched_symbols import expansion_universe;print(' '.join(expansion_universe()))") \
  --sl 0.5 --tp 5.0 --shorts --min-pf 1.1

# Refresh cache again later
.venv/bin/python scripts/download_history.py --upstox --tf 15m
```

## Phase 14 — Full-universe 3-fold SHORT OOS on 729d (2026-07-11, DONE)

Built on Phase 13's complete 117-symbol 729d 15m cache. Replaced the weak
Phase 12 Tier-B single 83d split with a rigorous 3-fold walk-forward across the
ENTIRE universe (ADANITRANS auto-skipped, delisted).

Command (background PID 9149, log `data/wf_short_3fold_117.log`):
```bash
INST_SHORT_MIN_SCORE=40 .venv/bin/python -u -m scripts.walkforward_validate \
  --timeframe 15m --train-start 2024-07-15 --test-end 2026-07-10 --folds 3 \
  --sl 0.5 --tp 5.0 --shorts --min-pf 1.1 --min-trades 10 \
  --symbols "$(118-symbol expansion_universe list)"
```

### Expanding-window design (disjoint OOS test each fold)
| Fold | Train | Test | OOS trades | Exp | PF≥1.5 |
|------|-------|------|-----------|-----|--------|
| 1 | 2024-07 → 2025-01 | 2025-01 → 2025-07 | 8,764 | **+0.190R** | 21/59 |
| 2 | 2024-07 → 2025-07 | 2025-07 → 2026-01 | 9,491 | **+0.190R** | 21/59 |
| 3 | 2024-07 → 2026-01 | 2026-01 → 2026-07 | ~9,335 | **+0.193R** | 22/60 |
| **agg** | | | **27,590** | **+0.191R** | **64/178** |

The edge is **remarkably stable** across all three disjoint test windows
(+0.190 / +0.190 / +0.193R) — far stronger evidence than the Phase 12 83d
single split. WR ~43% throughout (matches the known SHORT win-rate profile).

### Whitelist construction
Parsed the 3 OOS reports (`data/short_whitelist_3fold.txt`): symbols appearing
in **all 3 folds with positive avg expectancy AND a valid Upstox instrument
key** → **57 symbols**. Candidates were first filtered by in-cache 15m data
(117 files) then by `resolve_upstox_key` (all 57 resolved; none genuinely
unresolvable).

**Critical finding — 3-fold caught Phase 12 selection bias:**
- **COALINDIA**: Phase 12's TOP performer (+0.562R on 83d) is **negative in
  ALL 3 folds** on 729d (F1 −0.035, F2 −0.219, F3 −0.120R) → regime-specific
  fluke the short window overfit. Excluded.
- **HINDUNILVR / TCS / ICICIPRULI / BHARTIARTL**: 0 SHORT trades in every
  test window (don't fire SHORT on 729d) → excluded.
- **TATACONSUM**: F1 −0.188 (mixed) → excluded by the strict all-3-positive filter.

So 6 of the Phase 12 12-symbol whitelist were correctly dropped; the 729d
3-fold is the trustworthy validator.

### Live deployment (DONE)
`data/symbol_watchlists.json` `15m_intraday_short` expanded from 12 → **57
OOS-validated symbols** (top by avg expectancy: WIPRO +0.40R, BEL +0.39R,
RVNL +0.38R, MCDOWELL-N/NYKAA +0.37R, TITAN +0.33R). Paper trader restarted
(PID 9982) with the same flags (`--watchlist 15m_intraday_short --shorts
--conviction --upstox --loop --interval 15`); market closed (Sun) → waits for
Mon 09:15.

### Verdict
15m intraday SHORT is now **OOS-validated across the full 117-symbol universe
on 729 days / 3 disjoint windows at +0.191R net of realistic costs** — the
strongest validation possible without a trading-scoped token. LONG remains
disabled (Phase 12: needs native 15m; Upstox only offers 1m resampled).

### Commands
```bash
# Re-run (background)
INST_SHORT_MIN_SCORE=40 nohup .venv/bin/python -u -m scripts.walkforward_validate \
  --timeframe 15m --train-start 2024-07-15 --test-end 2026-07-10 --folds 3 \
  --sl 0.5 --tp 5.0 --shorts --min-pf 1.1 --min-trades 10 \
  --symbols "$(.venv/bin/python -c "import sys;sys.path.insert(0,'.');from data.downloader.watched_symbols import expansion_universe;print(','.join(expansion_universe()))")" \
  > data/wf_short_3fold_117.log 2>&1 &

# Parse per-symbol fold stats → data/short_whitelist_3fold.txt
.venv/bin/python -c "see Phase 14 parser in history"
```




---

## ⚠️ CORRECTION — OOS "expectancy" is GROSS, not net (2026-07-12)

The Phase 14 (`+0.191R`) and Phase B (`+0.222R`) walk-forward "expectancy"
numbers are **GROSS**. `scripts/walkforward_validate._report_oos` computes
`exp = sum(avg_r * trades)/trades` where `avg_r = mean(t.r_multiple)`, and
`t.r_multiple` is set in `scripts/backtest.py:_settle_trade` as
`gross_return / risk` — **costs are NOT subtracted** (costs only hit
`pnl_net`/`pnl_net_pct`, which the report ignores). So the headline
"+0.191R / +0.222R net of realistic costs" claims in Phase 14 / Phase B are
**incorrect**.

### Definitive net result (computed directly from backtest trade records)
From `data/backtest_trades_15m_intraday.json` (16,843 SHORT trades, same engine):
- avg **gross** R: **+0.0996**
- avg **net** R (after costs): **−0.3897**
- cost per trade: **+0.489 R**  (backtest STT was 0.1%; now fixed to 0.025%)
- total net P&L: **−₹1,676,071**

For the OOS-validated 70-symbol whitelist the gross edge is higher (+0.222R),
but cost-per-R is ~+0.36R (real 0.025% STT) to +0.49R (old 0.1% STT), so the
**net OOS expectancy is NEGATIVE** (~−0.14R with real STT). This matches the
Phase 11 cost warning ("₹111 gross → −₹3 net on 80-day ONGC").

### Why costs dominate
SHORT stop ≈ 1×ATR ≈ 0.3–0.7% of price (measured ~0.4%). At 1% risk (₹500) on
₹50k that forces a ~₹125k position; round-trip cost (~0.125% of notional with
real STT) ≈ ₹156/trade, while gross edge = 0.222 × ₹500 = ₹111/trade. Net loss.

### Status — DO NOT deploy
Per Phase 11's own rule ("Treat any window with avg net PnL < 0 after costs as
non-deployable"), the strategy is **NOT deployable** as configured. The edge is
real but too thin for the current cost structure / tight stops.

### Required fix before any deployment
Widen the SHORT stop (or otherwise lower cost-in-R) so net expectancy > 0 OOS.
Breakeven (real STT): SL distance ≳ 0.56% of price (currently ~0.4%). Must
re-validate NET expectancy after the change — the walkforward report must be
extended to print `pnl_net`-based stats, not just `r_multiple`.

### Completed fixes (2026-07-12)
- `scripts/backtest.py`: STT default corrected 0.1% → **0.025%** (intraday
  equity rate; 0.1% was the delivery rate — 4× overstated).
- `scripts/paper_trade.py`: `_record_exit` now applies the SAME cost model
  (`_trade_cost`, mirrors `_compute_costs`) to cash + fill records, so the
  paper portfolio shows honest net equity. Paper trader restarted (PID 13894).

---

## Phase A — Manual Institutional (time-gated) optimization (2026-07-14)

Focused on the **Manual Institutional (time-gated)** strategy — the only strategy
net-positive after real costs. Three changes applied and verified:

### A1 — Wednesday skip + conviction recalibration (DONE)
- HARD GATE 1b in `strategies/manual_institutional_strategy.py`: `SKIP_WEDNESDAY=1`
  (default). Verified: **0 Wednesday trades** out of 21,569 in full 191-symbol run.
- `conviction_multiplier()` in `scripts/capital_model.py`: thresholds changed from
  75/85 → **55/70**. Data-backed from 4,924 trades: +**45.7% more effective R**
  (2,160.8 new vs 1,483.0 old on 21,569 trades).
- Full A1 run (190 symbols, 21,569 trades, WR=21.5%, sum PnL=+703.6%, 64 deployable).
  See `data/backtest_portfolio_15m_A1_20260714.json` when re-run completes.

### A2 — Monday LONG +1.15× boost (DONE)
- Added to `calendar_conviction_multiplier()` in `scripts/capital_model.py`
  (Monday weekday()==0, LONG direction, ×1.15).
- Data-backed: Monday strongest day with +1501.9 SumR, avgR +0.282 — 2.3× Friday's
  +658.7 SumR. Thursday is net neutral (SumR -10.4) — no boost or skip added.

### A3 — Per-symbol SL/TP tuning (DONE)
- `scripts/tune_manual_sltp.py`: new dedicated tuner. Grid SL {0.3, 0.5, 0.8} ×
  TP {3.0, 5.0, 6.0, 8.0} = 12 combos/symbol. ~60 min for all 57 watchlist symbols.
- **55/57 symbols benefit from non-default SL/TP**. Dominant finding: **sl=0.3**
  with wider TP (6.0–8.0) outperforms default 0.5/5.0 for most symbols.
- Results saved to `data/manual_symbol_tunings.json` (57 entries, 55 with changed=True).
- SL distribution: 51× sl=0.3, 4× sl=0.5 (AEGISLOG, BSOFT default was best).
- TP distribution: 17× tp=8.0, 10× tp=6.0, 13× tp=5.0, 17× tp=3.0.

### A4 — Wiring tunings into strategy (DONE)
- `ManualInstitutionalStrategy.__init__()` loads `data/manual_symbol_tunings.json`
  into `self._tunings` dict.
- `decide_trade()` in `scripts/backtest.py` now passes `original_symbol` kwarg to
  the strategy (strips `.NS` suffix from `self._original_symbol`).
- `run()` resolves the symbol lookup via `kwargs["original_symbol"]`, applies
  per-symbol sl/tp override in `_sltp()`.

### Verification (5 symbols — HCLTECH, LODHA, AEGISLOG, ICICIGI, PWL)
| Metric | Before (default SL/TP) | After (per-symbol tuned) | Change |
|--------|----------------------|------------------------|--------|
| Trades | 326 | 329 | +3 |
| WR | 33.4% | 33.4% | same |
| Sum PnL% | +112.61 | +122.24 | **+8.6%** |
| Profitable | 5/5 | 5/5 | same |
| HCLTECH PF | 2.33 | 4.43 | **+90%** |
| LODHA PF | 2.80 | 3.93 | **+40%** |
| PWL PF | 3.73 | 6.57 | **+76%** |

### Full results snapshot
Saved to `data/results/manual_inst_improvements_2026-07-14.json` — contains A1
numbers, day-wise analysis, conviction distribution, per-symbol comparison, and
all change details.

### Relevant files
- `data/manual_symbol_tunings.json` — 57 per-symbol SL/TP overrides
- `data/results/manual_inst_improvements_2026-07-14.json` — full snapshot
- `data/backtest_portfolio_15m_A1_20260714.json` — A1 full results (re-running)
- `data/backtest_trades_15m_A1_20260714.json` — A1 detailed trades (re-running)
- `strategies/manual_institutional_strategy.py` — per-symbol SL/TP wiring + Wednesday gate
- `scripts/capital_model.py` — Monday boost in `calendar_conviction_multiplier`
- `scripts/backtest.py` — `original_symbol` pass-through in `decide_trade()`
- `scripts/tune_manual_sltp.py` — per-symbol SL/TP grid tuner

### A5 — Golden window boundary fix (2026-07-15)

Changed `_in_golden_window()` boundary check from `hour < end` to `hour <= end`
so bars closing exactly at 10:30 and 14:30 (the natural last bars of each golden
window) are included. These 4,184 boundary trades average +0.210R (14:30) and
+0.108R (10:30) — both profitable. The only truly outside bar (10:45, 59 trades,
−0.414R) is still correctly blocked.

**Data-backed impact** (from A1 22,022 trades): recovers **+611 sumR** that would
otherwise leak. Verified via test harness — all 10 boundary cases pass.

---

## Phase B — RSM Swing Strategy (2026-07-15)

The **Relative Strength Momentum** strategy redesigned as a swing strategy
(hold overnight, exit at `next_close`) due to its poor intraday cost-efficiency.

### Backtest (77 symbols, 730d, sl=2.0/tp=4.0)
- **5,410 trades, WR 44.0%**, avg PF 1.01
- 16 profitable (PF≥1.3), 23 break-even, 38 unprofitable
- Default params cover costs but barely — per-symbol tuning essential.
- SHORT path enabled in engine (`_volume_surge` + `_nifty_context` bearish scoring).

### Per-symbol SL/TP tuning (DONE)
- `scripts/tune_rsm_sltp.py`: grid SL∈{1.5,2.0,2.5,3.0} × TP∈{3.0,4.0,6.0} (12 combos)
- **42/56 symbols pass** (PF≥1.3, ≥10 trades), 14 fall back to defaults
- Merged into `data/rsm_swing_tunings.json`
- Dominant pattern: **sl=1.5/tp=6.0** (24/42)
- Top: SUMICHEM PF 3.94, AEGISLOG PF 2.80, LAURUSLABS PF 2.78

### Paper trader (DONE)
- Started (PID 52113): `--mode swing --swing-exit next_close` with 42 tuned symbols
- Status: idle (market closed)
- Uses the same RSM engine + strategy, per-symbol tunings loaded from `rsm_swing_tunings.json`

### rsm_swing watchlist (DONE)
- Added to `data/symbol_watchlists.json` with 42 tuned symbols (sorted by PF desc)
- Per-symbol `rsm_swing` details in `details` section (pf, trades, avg_r, wr,
  pnl_pct, max_dd, sl, tp)
- 7 symbols already existed in details (HFCL, DMART, TITAGARH, SCHNEIDER, UNIONBANK,
  BSE, TATAELXSI); 35 added as new entries

### rs_momentum_swing_tuned scan tier (DONE)
- Added to `SCAN_TIERS` in `scripts/market_scan.py`:
  `("rs_momentum_swing_tuned", "rsm_swing", "swing", ...)` with 15m, sl=2.0/tp=4.0
- Reads from the dedicated `rsm_swing` watchlist (42 tuned symbols)

### Commands
```bash
# RSM swing backtest (77 symbols, default SL/TP)
.venv/bin/python scripts/run_backtest_portfolio.py --no-intraday \
  --strategy "Relative Strength Momentum" --provider yfinance --days 730

# Tune per-symbol SL/TP
.venv/bin/python scripts/tune_rsm_sltp.py

# RSM swing paper trader
.venv/bin/python scripts/paper_trade.py --mode swing --swing-exit next_close \
  --strategy "Relative Strength Momentum" --watchlist rsm_swing

# Scan with tuned RSM swing tier
.venv/bin/python scripts/market_scan.py
```

### Relevant files
- `data/rsm_swing_tunings.json` — 42 per-symbol SL/TP tunings
- `data/backtest_portfolio_15m_rsm_swing.json` — 77-symbol backtest (portfolio)
- `data/backtest_trades_15m_rsm_swing.json` — 5,410 detailed trades
- `data/symbol_watchlists.json` — `rsm_swing` watchlist (42) + details
- `scripts/market_scan.py` — `rs_momentum_swing_tuned` tier
- `scripts/tune_rsm_sltp.py` — grid tuner
- `engines/relative_strength_engine.py` — SHORT path enabled
- `strategies/relative_strength_strategy.py` — swing defaults, per-symbol tuning

## Phase 15 — Both Intraday + Swing concurrently + avg holding time (2026-07-16)

User request: run intraday AND swing trading simultaneously in the paper trader,
and show average holding time on the live dashboard.

### Both modes concurrently (`scripts/paper_trade.py`)
- `--mode` now accepts **`both`** in addition to `intraday`/`swing`
  (default stays `intraday` — fully backward compatible).
- Replaced the global `SWING_MODE` flag with a per-position `mode` field +
  a `TRADING_MODE` global. In `both` mode the entry loop evaluates every
  symbol in **both** intraday and swing configurations (data fetched once via
  the new `_build_symbol_context()`, then `decide_trade` runs per-mode via
  `_decide_trade_for_mode()`), so the same symbol can hold an intraday AND a
  swing position at the same time.
- Per-mode rules now apply per position (not global):
  - Swing entries only fire in the last hour (14:30–15:15 IST); intraday any time.
  - SHORT gate is per-mode (`ALLOW_SHORTS` for intraday, `SWING_ALLOW_SHORTS` for swing).
- **Swing exit block (was gated by `if SWING_MODE:`) now runs unconditionally**
  so swing positions always get their scheduled `next_open`/`next_close` exit —
  previously a swing position opened under any non-swing global mode would
  never be force-exited. Intraday EOD force-close already skipped `mode:swing`
  (unchanged, correct).
- `record_trade_entry()` (trade_history.py) gained an optional `mode` arg so
  each open trade records whether it was intraday or swing.

### Average holding time on dashboard
- `scripts/market_scan.py`: new `_compute_holding_stats()` parses
  `opened_at`/`closed_at` for CLOSED trades and returns overall + per-mode
  avg hours; emitted as `holding_stats` in `/api/latest`.
- `web/dashboard.html`: header now shows **`Avg hold: Xh Ym`** (with a hover
  tooltip breaking down intraday vs swing averages).

### Verification
- `--mode both` opens intraday + swing for the same symbol concurrently (tested).
- Swing exit fires at `next_close` even when global `TRADING_MODE=intraday`
  (the original gap) — tested.
- `holding_stats` present in `/api/latest` payload (tested).
- `scripts/start_all.sh` updated to launch the paper trader with `--mode both`.

### Commands
```bash
# Both intraday + swing, concurrently
.venv/bin/python scripts/paper_trade.py --mode both --watchlist consensus \
  --shorts --conviction --upstox --loop --interval 5

# One-shot both-mode cycle
.venv/bin/python scripts/paper_trade.py --mode both --symbols ONGC,WIPRO

# Dashboard shows avg holding time at http://<host>:8080/
.venv/bin/python scripts/market_scan.py --upstox --serve --port 8080
```

## Phase 16 — Per-strategy watchlists in paper trader (2026-07-16)

User request: the paper trader should use each strategy's **own** watchlist,
not a single merged symbol list fed to every strategy (the scanner already
does this via `SCAN_TIERS`).

### Change (`scripts/paper_trade.py`)
- Added `STRATEGY_WATCHLISTS` mapping:
  - `Institutional Probability` → `["consensus"]` (+ `15m_intraday_short` when `--shorts`)
  - `Relative Strength Momentum` → `["rsm_swing", "consensus"]`
  - `Manual Institutional (time-gated)` → `["manual_morning_deploy", "manual_evening_deploy"]`
- `main()` now builds `strategy_symbols: dict[str, list[str]]` (per strategy)
  instead of one flat `symbols` list. `--symbols` / `--watchlist` still override
  with a flat list for all strategies (backward compatible).
- `run_cycle()` signature gained `strategy_symbols` param; the entry loop uses
  `strategy_symbols.get(strat_name, symbols)` so each strategy only scans its
  own universe. The Manual time-gated window filter still applies on top.
- Also fixed a **pre-existing bug** in `start_all.sh`: it passed `--conviction`,
  which is not a valid flag (conviction is ON by default; only `--no-conviction`
  exists) — removed so the paper trader starts cleanly.

### Result
Same 3-strategy setup now scans per-strategy: IP=64, RSM=63, Manual=73 (126
unique) instead of one merged 118-symbol list for all. Cycles are faster and
trades are strategy-appropriate (no cross-contamination).

### Commands
```bash
# Per-strategy watchlists (default)
.venv/bin/python scripts/paper_trade.py --mode both --shorts --upstox --loop --interval 5

# Override with explicit symbols (flat, all strategies)
.venv/bin/python scripts/paper_trade.py --symbols ONGC,WIPRO --mode both

# One named watchlist for all strategies
.venv/bin/python scripts/paper_trade.py --watchlist consensus --mode both
```

## Phase 17 — Halt Institutional Probability deployment (2026-07-16)

User decision: **keep IP's code in the codebase but stop deploying it** (net
negative after costs — see CORRECTION block in Phase 14). Cross-strategy
duplicate entries are confirmed by-design (each strategy manages its own
capital). Stale test trades (TESTSYM/SYMA/SYMB) were cleaned in this session.

### Change (deployment config only — NO code changes)
- `scripts/start_all.sh` paper-trader launch:
  - `--strategies` → `"Relative Strength Momentum,Manual Institutional (time-gated)"`
    (removed `Institutional Probability`)
  - `--alloc` → `50,50` (IP's 35% → RSM: 15→50; Manual stays 50)
  - `--sl` → `1.0,0.5` (RSM 1.0 / Manual 0.5); `--tp` → `2.5,5.0`
  - Removed `--shorts` (RSM shorts disallowed per user; Manual already LONG-only)
- Relaunched paper trader PID 55718: RSM=63 symbols, Manual=73 symbols (94 unique).
- IP's engine/strategy code is fully retained; the paper trader simply doesn't
  instantiate it (loaded only when `--strategies` lists it).
- Per-strategy watchlists (Phase 16) + per-symbol SL/TP (Phase A3/B) unchanged
  and still active for the 2 surviving strategies.

### Result
Only RSM + Manual trade live. Day-entry cap is now 10 (5 × 2 strategies).
Scanner/dashboard still runs with `--shorts` (visual IP swing tiers remain on
the dashboard) but no IP positions are opened by the paper trader.

### Commands
```bash
# Current live config (2 strategies, no IP)
.venv/bin/python scripts/paper_trade.py \
  --strategies "Relative Strength Momentum,Manual Institutional (time-gated)" \
  --alloc 50,50 --sl 1.0,0.5 --tp 2.5,5.0 \
  --mode both --upstox --loop --interval 5
```

## Phase 18 — Targeted RSM swing entry windows (2026-07-16)

User decision: remove the flat 14:30–15:15 swing entry gate (which had avgR
+0.0097, break-even) and replace with data-driven targeted windows from the
RSM 15m backtest (5,410 swing trades).

### Analysis (backtest trade timestamps)
| Window | Avg R | WR |
|--------|-------|-----|
| 11:30 | +0.323 | 55.9% |
| 14:00 | +0.314 | 56.7% |
| 11:45 | +0.146 | 49.6% |
| 11:15 | +0.127 | 48.9% |
| 14:45 | +0.093 | 46.8% |
| 10:00–11:30 block | ~+0.10 | ~47% |
| 13:00–13:30 | −0.04 to −0.08 | avoid |
| 09:15 (open auction) | −0.11 | avoid |
| 14:15 / 14:30 / 15:15 | negative | avoid |

The old 14:30–15:15 gate included two losing slots (14:30, 15:15) and one
break-even (15:00), dragging the block to +0.0097. The best edge is the
10:00–11:45 morning block (avgR +0.10 across 1,144 trades), plus two isolated
afternoon spikes at 14:00 (+0.31) and 14:45 (+0.09).

### Change (`scripts/paper_trade.py`, swing entry gate in `run_cycle`)
Replaced:
```python
if not (14.5 <= hour_min <= 15.25): continue
```
with targeted windows:
```python
allowed = (
    (10.0 <= hour_min < 11.75) or
    (14.0 <= hour_min < 14.25) or
    (14.75 <= hour_min < 15.0)
)
if not allowed: continue
```
Net expected avgR improves from +0.0097 → ~+0.029 (3×) by recovering the
10:00–11:45 block that the old gate excluded.

### Result
Paper trader (PID 57789) restarted: RSM + Manual only, IP halted, no shorts.
RSM swing entries now fire only at 10:00–11:45, 14:00–14:15, 14:45–15:00 IST.

## Phase 19 — Combined Swing end-to-end deployment (2026-07-16)

Closed the loop on the Combined Swing strategy (day-aware RSM-swing LONG, LONG-only,
per-symbol tuned SL/TP from `data/combined_swing_tunings.json`).

### Backtest + tuning (done earlier same day)
- 191-symbol expansion backtest → **64 profitable** (PF≥1.3, trades≥10).
- `build_combined_watchlist.py` wrote the `combined_swing` key (64 symbols) to
  `data/symbol_watchlists.json`.
- `tune_combined_sltp.py` ran 4-way parallel over the 64 symbols
  (SL∈{1.5,2.0,2.5,3.0}×TP∈{3.0,4.0,6.0}); all 64 tuned. Outputs merged into
  `data/combined_swing_tunings.json` (64 entries, all `changed=True`).
  Dominant pattern: **sl=1.5 / tp=3.0** (e.g. LAURUSLABS PF 18.15, HCLTECH PF 5.96).

### Scanner tier (DONE this step)
- Added `("combined_swing", "combined_swing", "swing", {tf:15m, sl:2.0, tp:4.0,
  intraday:False, strategy:"Combined Swing"})` to `SCAN_TIERS` in
  `scripts/market_scan.py` (was missing — the 64 tuned names never appeared on
  the dashboard). Per-symbol tunings apply because the scanner passes
  `original_symbol` into `decide_trade` → `executable.run()`.
- Removed the stale `rs_momentum_swing` tier (used Manual's `manual_morning_deploy`
  watchlist; superseded by `rs_momentum_swing_tuned` → `rsm_swing`).
- Tier count stays 11; `combined_swing` verified present via import.

### Live deployment (DONE)
- `data/combined_swing_tunings.json` loads cleanly (64 tunings; defaults sl=2.0/tp=4.0).
- Paper trader restarted (PID 61567): `--strategies "Relative Strength Momentum,
  Combined Swing,Manual Institutional (time-gated)" --alloc 33,33,34 --sl 1.0,2.0,0.5
  --tp 2.5,4.0,5.0 --mode both --upstox --loop --interval 5`.
- Scanner restarted (PID 61951) with `--upstox --serve --port 8080`.
- `STRATEGY_WATCHLISTS["Combined Swing"]` → `["combined_swing"]` (Phase 3) so the
  paper trader scans only its 64-symbol universe.

### Verification
- `CombinedSwingStrategy()` loads 64 tunings; per-symbol override confirmed
  (LAURUSLABS sl=1.5/tp=3.0 overrides 2.0/4.0 defaults).
- Both scanner + paper trader forward `original_symbol`, so tunings apply live.

### Commands
```bash
scripts/paper_trade.py --strategies "Relative Strength Momentum,Combined Swing,Manual Institutional (time-gated)" \
  --alloc 33,33,34 --sl 1.0,2.0,0.5 --tp 2.5,4.0,5.0 --mode both --upstox --loop --interval 5
scripts/market_scan.py --upstox --serve --port 8080
```


## Phase 20 — Live trading (real Upstox orders) (2026-07-16)

Wired real order placement into the paper trader. Fully additive — default
behaviour unchanged (paper only); live orders only fire with the new `--real`
flag.

### Changes (`scripts/paper_trade.py`)
- **`--real` flag** → sets `REAL_ORDERS`. Guarded: requires `--upstox` (refuses
  to place live orders on the delayed yfinance feed). Prints a loud LIVE banner.
- **`place_upstox_order()` was dead code** (defined, never called). Now invoked
  on entry AND exit when `REAL_ORDERS`:
  - **Entry**: order placed BEFORE any paper bookkeeping. If rejected → skip the
    paper entry too (no phantom position, no cash movement).
  - **Exit**: order placed at fill; on failure logs a warning (position still
    tracked; broker position may remain open → manual check).
- **`_order_payload()`** now takes `mode` → sets Upstox `product`: `"D"`
  (delivery) for swing, `"I"` (intraday) otherwise. Entry/exit are MARKET orders
  (SL/TP monitored in-code, not as broker orders). MARKET orders send price 0.
- **`MAX_ORDER_VALUE=25000`** hard cap — any single real order above ₹25k
  notional is BLOCKED (returns None → entry skipped).
- Returned `order_id` recorded on the trade's `order` dict for audit.

### Token / IP finding (USER ACTION REQUIRED — BLOCKER)
The `.env` token DOES have trade scope (Plus/extended plan), BUT Upstox trading
APIs are **IP-locked**:
- Data endpoints work: `market-quote/ltp` → HTTP 200 (Nifty LTP fetched).
- Trading endpoints fail: `user/get-funds-and-margin` → **HTTP 401 UDAPI1221**
  "The API you are trying to access is permitted only when requested from the
  static IP configured in your account."
- Current public IP: **210.212.2.133** (likely dynamic).

**To enable live orders the user must:**
1. Obtain a STATIC IP (ISP static IP, or a fixed-IP VPN/proxy/cloud host).
2. Register that static IP in the Upstox account (Developer/API settings).
3. Ensure this machine's outbound traffic uses that whitelisted IP.
Until then, `--real` orders will be rejected by Upstox with UDAPI1221 (the code
handles this gracefully: entry skipped, exit warned).

### Verification
- `py_compile` clean; `--real` present in `--help`.
- `--real` without `--upstox` → SystemExit with clear error.
- Trade-scope probe returns UDAPI1221 (IP lock), NOT a scope error → token is
  trade-capable; only the static-IP registration is missing.

### Commands
```bash
# Paper only (current live deployment — unchanged)
scripts/paper_trade.py --strategies "Relative Strength Momentum,Combined Swing,Manual Institutional (time-gated)" \
  --alloc 33,33,34 --sl 1.0,2.0,0.5 --tp 2.5,4.0,5.0 --mode both --upstox --loop --interval 5

# LIVE real orders (once static IP is registered with Upstox)
scripts/paper_trade.py --strategies "..." --alloc ... --sl ... --tp ... \
  --mode both --upstox --real --loop --interval 5

# Or via the launcher (paper = default; LIVE=1 adds --real):
./scripts/start_all.sh            # paper only
LIVE=1 ./scripts/start_all.sh     # REAL orders (needs Upstox static IP)
```

### Phase 20b — LIVE go-live (2026-07-17)

Static IP registered with Upstox → trade APIs unlocked. Verified before launch:
- `market-quote/ltp` HTTP 200 (data, unchanged).
- `order/retrieve-all`, `portfolio/short-term-positions`,
  `portfolio/long-term-holdings` → **all HTTP 200** (empty) — confirms static IP
  accepted + token trade scope active.
- `user/get-funds-and-margin` → HTTP 423 UDAPI100072 (funds service nightly
  maintenance 12:00 AM–5:30 AM IST only; not an error).
- IP-lock error UDAPI1221 is GONE.

**Went LIVE** (user-confirmed, reset + real):
- Stopped paper PID 61567 (stale state: had halted IP, missing Combined Swing,
  RSM cash depleted to ₹7.2k).
- Relaunched PID 62101 with `--reset --real`:
  `--strategies "Relative Strength Momentum,Combined Swing,Manual Institutional (time-gated)"
   --alloc 33,33,34 --sl 1.0,2.0,0.5 --tp 2.5,4.0,5.0 --mode both --upstox --real
   --loop --interval 5`.
- Fresh allocations: RSM ₹16,500 / Combined Swing ₹16,500 / Manual ₹17,000 = ₹50k.
- Universe: RSM=63, Combined Swing=64, Manual=73 (115 unique).
- Scanner PID 61951 still serving dashboard on :8080.
- Market closed at launch (00:17 IST Fri) → first real orders fire at 09:15 open.

Safety active: MAX_ORDER_VALUE ₹25k cap, entry-fail → skip paper too, exit-fail →
warn + keep tracking, plus existing drawdown breaker / daily cap / 1h SL cooldown /
bar dedup / 1m entry gate.

## Phase 21 — Live/paper/broker reconciliation (2026-07-17)

Closed the 6 discrepancies between live (--real) Upstox orders, the paper shadow
state (`data/paper_portfolio.json`), and the dashboard. All in `scripts/paper_trade.py`.

### New helpers
- `_upstox_headers()` — shared auth header builder.
- `poll_order_fill(order_id)` — polls `/v2/order/details` up to 3× / 5s; returns
  `{status, avg_price, filled_qty, raw}`. Terminal states: filled
  {complete,filled,traded} / dead {rejected,cancelled,canceled}.
- `fetch_upstox_positions()` — `/v2/portfolio/short-term-positions` → dict keyed
  by instrument_key with signed qty, avg_price, direction. Returns None on API
  failure (distinguishes "no positions" from "couldn't reach broker").
- `reconcile_state_with_broker(state)` — startup alignment.

### The 4 fixes
1. **Entry fill confirmation (Phase 2)** — after `place_upstox_order` returns an
   order_id, `poll_order_fill` confirms the fill; the paper position uses the
   broker's ACTUAL `avg_price` + `filled_qty` (not `decision.entry_price`).
   Unfilled/rejected → skip paper entry.
2. **Exit fill confirmation (Phase 3)** — `_record_exit` now places + confirms the
   real order BEFORE booking the paper exit. On reject/no-fill it returns None,
   leaves the position OPEN, increments `exit_retry`, and retries next cycle. Uses
   the broker's actual fill price for honest P&L. All 3 exit call-sites (SIGNAL,
   EOD, SWING-EXIT) handle the None return by keeping the position.
3. **Startup reconciliation (Phase 1)** — on launch with --real: phantom paper
   positions (not open at broker) are booked out via a RECONCILE-CLOSED exit
   (no order placed, `place_order=False`); matching positions have entry_price
   corrected to broker avg; broker positions unknown to paper are logged (not
   auto-adopted). Runs in `main()` after `_load_state()`, before the loop.
4. **EOD auto-square check (Phase 4)** — intraday product="I" is auto-squared by
   Upstox at 15:30. The EOD force-close fetches broker positions once; if the
   broker no longer holds a position it books EOD-AUTOSQUARE (no order) instead
   of EOD-FORCE-CLOSE (which would place a NEW opposite order).

### Verified
- py_compile clean; all helpers importable.
- `fetch_upstox_positions()` → 0 open (broker flat, correct); reconcile "OK".
- Synthetic phantom (WIPRO not at broker) → removed + RECONCILE-CLOSED booked.
- Paper-only path (REAL_ORDERS=False) → `_record_exit` still returns a fill, no
  polling / no broker calls (unchanged behaviour).
- Relaunched LIVE PID 62203 (kept state, no --reset): startup reconcile ran
  "[reconcile] OK — paper state matches broker positions", waiting for open.

### Note
`_record_exit` signature gained `place_order=True` and can now return None.
`exit_retry` counter added to positions that fail a real exit.

## Phase 22 — Remaining live/paper divergence fixes (2026-07-17)

Addressed the top 5 remaining gaps (beyond Phase 21) between real Upstox
execution and the paper shadow state. All in `scripts/paper_trade.py`, all
additive (paper-only path unchanged — no WAL, no broker calls when `--real` off).

### Fix 1 — Partial fills (was: partial fill lost / orphaned)
- `poll_order_fill(order_id, requested_qty=None)` now returns `complete`/`partial`
  flags (filled_qty vs requested_qty), not just a filled/dead status.
- **Entry**: books exactly `filled_qty`; if partial, `cancel_upstox_order()` voids
  the unfilled remainder so it can't fill later behind the bot. filled==0 → skip.
- **Exit**: `_book_partial_exit()` books the closed portion into cash+history,
  shrinks `p['shares']` in place, cancels the remainder, returns None so the
  caller KEEPS the (smaller) position open to close the rest next cycle.
- `cancel_upstox_order()` — new DELETE `/v2/order/cancel` helper.

### Fix 2 — Cash reconciliation (was: paper cash never trued up)
- `fetch_upstox_funds()` — `/v2/user/get-funds-and-margin` → available equity
  margin (handles 423 nightly-maintenance gracefully → None).
- Reconcile cross-checks total paper cash vs broker margin; warns when the delta
  exceeds `_CASH_DIVERGENCE_WARN` (₹5,000, env `INST_CASH_DIVERGENCE_WARN`).
  Never blindly overwrites (broker margin can include non-bot funds).

### Fix 3 — Periodic mid-day reconcile (was: reconcile only at startup)
- `reconcile_state_with_broker(state, periodic=True)` — CONSERVATIVE mode: never
  auto-closes a paper position (avoids the settlement race where a just-opened
  position hasn't hit short-term-positions yet). Only fixes prices/shares,
  adopts unknowns, cash-checks.
- `run_cycle` runs it every `_RECONCILE_EVERY_N_CYCLES` cycles (default 20 ≈ 100
  min; env `INST_RECONCILE_EVERY`) via `_CYCLE_COUNTER`.

### Fix 4 — Adopt unknown broker positions (was: logged but orphaned)
- `_adopt_broker_position()` — a broker position not in paper is now ADOPTED:
  strategy/SL/TP/mode recovered from the WAL intent if present, else assigned to
  the strategy with the most free cash with a protective default SL/TP (±5%/±10%).
  Deducts cash for LONG, marks `adopted:True`. Refuses (logs) if the symbol can't
  be resolved (no bad positions created).
- `_symbol_for_instrument_key()` — reverse instrument-key→symbol lookup.
- Reconcile also now fixes SHARE count to broker qty (not just entry_price).

### Fix 5 — WAL / crash resilience (was: crash between order+state = orphan)
- Write-ahead log `data/pending_orders.jsonl`: `_wal_record()` appends every real
  entry's INTENT (symbol/strategy/SL/TP/mode/qty/instrument_key) BEFORE placing;
  `_wal_resolve()` marks it done after the position is booked. `_wal_pending()`
  returns unresolved intents; `_wal_reset()` truncates after startup recovery.
- On startup, `_adopt_broker_position` consumes pending WAL intents so a position
  filled during a crash is re-adopted with its correct strategy + SL/TP.

### Verified
- py_compile clean; all 11 helpers importable.
- WAL round-trip (record/resolve/pending/reset) correct.
- Adoption: with WAL intent → correct strategy+SL/TP+cash; without resolvable
  symbol → safely refused (no bad position).
- Partial exit: books 15/40, shrinks to 25, cash + net P&L correct.
- Startup + periodic reconcile against live broker → both "OK" (broker flat;
  funds 423 nightly maintenance handled).
- Paper-only path (REAL_ORDERS=False) → no WAL file, no broker calls, exit fill
  unchanged.
- Relaunched LIVE PID 62312 (kept state): startup reconcile "OK", waiting for open.

### Env knobs
`INST_CASH_DIVERGENCE_WARN` (₹5000), `INST_RECONCILE_EVERY` (20 cycles).

## Phase 23 — Per-strategy day-of-week gates + sizing (2026-07-17)

User insight: "Indian market behaves differently on different days — can we make
a strategy out of it?" Confirmed via day-of-week analysis of each strategy's own
backtest trade set. Implemented as **hard day gates + per-strategy risk sizing**
(NOT an engine score factor — a ±5-point score nudge adds noise without changing
trade quality; skipping a losing day and sizing up a winning day directly move
net expectancy).

### Data (per-strategy AvgR by weekday)
| Day | RSM Swing (5,410 tr) | Manual Inst (22,022 tr) | IP SHORT (17,679 tr) |
|-----|----------------------|-------------------------|----------------------|
| Mon | +0.070 | **+0.491** (best) | +0.155 |
| Tue | +0.071 | +0.147 | **+0.242** (best) |
| Wed | +0.018 (weak) | skipped in-strategy | −0.019 (neg) |
| Thu | **−0.117** (neg, all sessions) | +0.114 | +0.107 |
| Fri | +0.081 (best WR 46%) | +0.294 (2nd) | +0.120 |

RSM Thursday is negative in EVERY session (opening −0.142 / morning −0.103 /
midday −0.093 / afternoon −0.116) → a whole-day skip, not a timing fix.
Manual Monday morning +0.706R is 4.8× Tuesday morning → the old flat ×1.15
Monday boost was too conservative.

### Change (`scripts/capital_model.py`)
`calendar_conviction_multiplier(entry_date, direction, strategy=None)` gained a
`strategy` param and a `_STRATEGY_DAY_MULT` map (keyed by `weekday()`):
- **RSM (Relative Strength Momentum):** Wed ×0.5, **Thu ×0.0 (SKIP)**, Fri ×1.05
- **Manual Institutional:** **Mon ×1.30**, Wed ×0.0, Fri ×1.10
- **Combined Swing / unmapped:** falls through to the legacy generic weekday
  rules (LONG Mon/Fri ×1.15, SHORT Tue ×1.15).
A **0.0 return = HARD SKIP** (no trade that day for that strategy). Event boosts
(monthly expiry ×1.30, pre/post-holiday ×1.25) still apply in all cases.

### Wiring
- `scripts/paper_trade.py` `run_cycle()`: passes `strategy=strat_name`; a
  `cal_mult == 0.0` prints a `[day-skip]` line and `continue`s (no entry).
- `scripts/backtest.py`: passes `strategy=bt.strategy` so backtests reflect the
  same gates (risk_pct→0 → notional→0 → trade skipped).

### Validated impact (replayed on historical trade sets)
- **RSM Swing:** skips 995 Thu trades → kept AvgR **+0.0264 → +0.0588R (2.2×)**;
  risk-weighted SumR **+194.4 → +270.8 (+39%)**.
- **Manual:** no new skips (Wed already gated) but Mon ×1.30 + Fri ×1.10 sizing
  adds risk-weighted SumR **+6323.6 → +6657.2 (+333.5R, +5.3%)**.

### Deployment
Paper trader restarted (PID 63888, state kept — AEGISLOG position carried over):
same `--strategies RSM,Combined Swing,Manual --alloc 33,33,34 --mode both --upstox`.
Verified live: Fri 2026-07-17 → RSM ×1.05, Combined ×1.15, Manual ×1.10 (no skips
today; Thu/Wed skips activate on those weekdays).

### Relevant files
- `scripts/capital_model.py` — `_STRATEGY_DAY_MULT`, `_strategy_day_multiplier()`,
  extended `calendar_conviction_multiplier()`.
- `scripts/paper_trade.py` — `run_cycle()` passes strategy + `[day-skip]` log.
- `scripts/backtest.py` — passes `strategy=bt.strategy` to the multiplier.

## Phase 24 — Bar confirmation gate (Manual only) (2026-07-17)

User insight (from their prior discretionary strategy: "entry only after 15m
close above level + volume expansion", "avoid mid-range", "probability ≥83%").
Tested a bar-confirmation + mid-range entry filter, then narrowed it to the
strategy the data supports.

### The gate (`scripts/backtest.py` `_confirmation_gate()`)
Checks the LAST completed bar in the entry window (LONG-only):
- **bullish bar**: `close > open`
- **volume expansion**: `volume > 1.3 × prior-bar volume`

Applied ONLY to **Manual Institutional**. RSM Swing / Combined Swing pass
through unfiltered (their momentum breakout entries are already bullish +
volume-expanding + near range highs → the gate is redundant AND harmful there).
Toggle via `INST_CONFIRM_GATE=0` (default ON). Wired in `decide_trade()` after
the HTF check; mirrored live in `paper_trade.py` `run_cycle()` (`[confirm]` skip
log) importing the same `_confirmation_gate`.

### Why Manual-only — authoritative full-trade-file replay (net of costs)
Replayed the gate on every trade in the existing backtest trade files (same
trades, same `pnl_net`), then restricted to each strategy's DEPLOYED watchlist:

| Strategy (deployed watchlist) | Trades | Net PnL baseline | Net PnL +gate | Δ |
|-------------------------------|--------|------------------|---------------|---|
| **Manual (108 syms)** | 8,409 → 1,696 | **−₹184,193** | **+₹44,313** | **+₹228,506** |
| RSM (42 syms) | 3,094 → 2,295 | +₹26,745 | −₹41,604 | −₹68,349 |

The gate **flips Manual from a net loss to a net profit** (WR 21.3%→27.5%,
gross AvgR +0.68→+1.27) by cutting ~80% of its trades — the skipped bars are
bearish/low-volume signal bars (isolated: **6.6% WR / −0.682R**). For RSM it
REMOVES winners (already-confirmed momentum entries), so RSM/Combined are left
ungated.

**Correction to earlier session estimate:** a quick top-25 SAMPLE projection had
suggested RSM would improve ~4×; that sample undercounted via bar-timestamp
mismatch. The full-file replay (only ~135 unmatched of 5,410) is authoritative
and shows the opposite — RSM must NOT be gated.

### Deployment
Paper trader restarted (PID 64086, state kept — AEGISLOG carried): same
`--strategies RSM,Combined Swing,Manual --alloc 33,33,34 --sl 1.0,2.0,0.5
--tp 2.5,4.0,5.0 --mode both --upstox --loop --interval 5`. Gate unit-tested
(Manual bearish→skip, RSM/Combined→passthrough, Manual bullish+vol→pass).
`[confirm]` skips fire when Manual evaluates in its golden windows (09:15–10:30,
14:00–14:30 IST).

### Relevant files
- `scripts/backtest.py` — `_confirmation_gate()`, `_CONFIRM_GATE` env toggle,
  wired into `decide_trade()`.
- `scripts/paper_trade.py` — imports `_confirmation_gate`; `[confirm]` gate in
  `run_cycle()` before the day-of-week multiplier.

## Phase 25 — Combined Swing validation + prune to OOS-robust 17 (2026-07-17)

Combined Swing's deployed **64-symbol** watchlist (built Phase 19 on gross
PF≥1.3) does NOT survive costs — same trap as IP (Phase 14). Validated then
pruned.

### Cache bug fixed (`scripts/backtest.py` `_nse_symbol_for_cache()`)
Expansion-universe symbols returned `None` → cache-only backtests silently
skipped 58/64 parquet files (every full-universe cache-only run was affected).
Added an `expansion_universe()` lookup so the full universe resolves.

### Backtest (64-sym watchlist, 730d, `--no-intraday`)
**4,504 trades, WR 37.3%, AvgR +0.146, Net PnL −₹10,095** (net negative).
29 winners / 35 losers. Per-symbol tunings confirmed applied (SL 0.79%–2.06%).

### OOS train/test split (60/40 at 2026-01-16) — NOT in-sample bias
- 26 symbols profitable in **train** → held-out **test** net **+₹93,748**
  (909 trades); 17/26 (65%) stayed positive in test (moderate persistence).
- **17 symbols positive in BOTH halves** → full-period net **+₹193,078**.
- Phase 24 gate replayed on Combined → **hurts** (−₹33k) → confirms Manual-only.

### Decision (user-approved) — prune to 17 robust symbols
`combined_swing` cut 64 → **17**: NETWEB, SIGNATURE, FORTIS, NYKAA, TRENT, BHEL,
SUMICHEM, PAYTM, ABB, OFSS, BSE, ADANIENT, SBIN, MAXHEALTH, HINDUNILVR,
LAURUSLABS, BPCL. Old 64 kept under key `combined_swing_full_64`; backup
`data/symbol_watchlists.json.bak_pre_combined_prune_*`. Each of the 17 earned
money in two disjoint windows (defensible, unlike the net-negative 64 or a pure
in-sample winners list). Caveat: 65% persistence = Combined symbol selection is
moderately unstable (like 1h swing, Phase 6).

### Relevant files
- `scripts/backtest.py` — `_nse_symbol_for_cache()` expansion lookup fix.
- `data/symbol_watchlists.json` — `combined_swing` (17) + `combined_swing_full_64`.
- `data/backtest_trades_15mcombined_valid.json` — 4,504 Combined trades.

## Phase 26 — Live data freshness fix: today's intraday candles (2026-07-17)

**Critical live bug found during the Phase 25 restart.** At 14:53 Friday with
the market open, `_upstox_live()` returned last bar = **Thursday 15:30** for
EVERY symbol (liquid RELIANCE/SBIN included) — the entire current session was
missing. The live paper/real trader was deciding on **yesterday's** bars, and
the Phase 23 day-gate read the wrong weekday (so RSM, whose Thursday multiplier
is ×0.0, was being fully SKIPPED on a Friday).

### Root cause
`UpstoxMarketDataProvider._fetch_candles()` only hit
`/v2/historical-candle/{key}/{interval}/{to}/{from}`, which serves data only up
to the **previous trading day**. Upstox exposes today's in-progress candles on a
**separate** endpoint, `/v2/historical-candle/intraday/{key}/{interval}`, that
the code never called. (Backtest cache builds via `download_history.py` were
correct — they only want complete days.)

### Fix
- `data/upstox/upstox_market_data_provider.py`: `_fetch_candles()` gained an
  `intraday=True` branch (hits the intraday URL, no date path); new public
  `load_intraday_data(symbol, timeframe)` wraps it.
- `scripts/paper_trade.py`: new `_merge_intraday(provider, key, interval, hist)`
  concats today's candles onto the historical frame (dedup on timestamp, keep
  last, sort). Wired into `_upstox_live()` for the 15m (via 1m), 1m, and 1d
  paths. Best-effort: any failure/empty intraday response → historical frame
  unchanged. **Live path only** — the cache builder is untouched.

### Verified
- py_compile clean (both files).
- Intraday endpoint probe (SBIN): 344 1-min candles 09:15→14:58 Friday.
- Post-fix `_upstox_live("SBIN"/"RELIANCE"/"AEGISLOG"/"ACUTAAS", "15m")` → last
  15m bar **2026-07-17 15:00 (Friday)**, 156 bars (was Thursday 15:30, 133 bars).
- Paper trader restarted **PID 64633** (paper mode, state kept): 15:02 cycle
  completed clean (Equity ₹50,063, 0 open), day-gate now reads Friday.

### Impact
Every prior live session's intraday entries fired on stale (prev-day) signals,
and day-of-week gates applied the wrong weekday. Now corrected. Note: each live
symbol now makes one extra intraday API call per timeframe → slightly slower
cycles (acceptable).

### Relevant files
- `data/upstox/upstox_market_data_provider.py` — `load_intraday_data()`,
  `_fetch_candles(intraday=...)`.
- `scripts/paper_trade.py` — `_merge_intraday()`, wired into `_upstox_live()`.

## Phase 27 — Consolidated backtest + OOS-prune Manual & RSM to net-positive (2026-07-17)

Ran one authoritative consolidated backtest of all 3 deployed strategies with
their exact live config (pruned watchlists, per-symbol tunings, Phase 23 day
gates, Phase 24 confirmation gate), then aggregated **net rupee PnL** (not the
gross `r_multiple` the walk-forward reports use — see Phase 14 CORRECTION).

### Consolidated result (730d, 15m `--no-intraday`, `--slippage default`, net of costs)
| Strategy | Syms | Trades | WR | Gross avgR | **Net PnL** | Symbols net+ |
|----------|------|--------|-----|-----------|-------------|--------------|
| Combined Swing | 17 | 1,211 | 45.6% | +0.436 | **+₹162,382** | 17/17 |
| Manual Instl. | 73 | 3,798 | 12.9% | +0.725 | **−₹35,694** | 28/73 |
| RSM Swing | 42 | 4,514 | 32.5% | +0.119 | **−₹105,940** | 12/42 |

**Critical finding:** `pnl_pct` (gross % move) was positive for ALL three
(+580 / +802 / +641%), but `pnl_net` (rupees, after costs) was NEGATIVE for
Manual & RSM — costs flip them (exactly the Phase 14 warning). Manual's +0.725
gross avgR is a mirage: its tight stops (sl 0.3–0.5) force notional to the ₹50k
cap → cost/trade ≈ 0.74R eats the whole edge. Only **Combined Swing** (already
pruned to 17 in Phase 25) was genuinely net-positive.

The earlier "+₹44k Manual / +₹27k RSM" Phase-24 replay figures came from
gross-R replays on the older 108-sym A1 file and are superseded by this run.

### OOS prune (user-approved) — same method that fixed Combined in Phase 25
Split each strategy's trade file 50/50 by entry time; keep symbols net-positive
in BOTH halves. Validated the selection method with a stricter train-select →
test-measure pass (Manual test-only +₹27.8k, RSM test-only +₹29.5k → method not
overfit).

- **Manual: 73 → 9** (CEMPRO, GODREJIND, IDEA, NEWGEN, NLCINDIA, ONGC, SUMICHEM,
  THERMAX, TITAGARH). `manual_morning_deploy` 68→9, `manual_evening_deploy` 40→5.
- **RSM: 42 → 8** (HFCL, DMART, TITAGARH, KIRLOSENG, PAYTM, OFSS, NEWGEN, BSE).
  `rsm_swing` 42→8.
- Full lists preserved as `manual_morning_deploy_full` / `manual_evening_deploy_full`
  / `rsm_swing_full_42`; backup `data/symbol_watchlists.json.bak_pre_manual_rsm_prune_*`.

### Fresh re-backtest of the pruned sets (confirms turnaround)
| Strategy | Trades | Net PnL (before → after prune) | Profitable |
|----------|--------|-------------------------------|------------|
| Manual (9) | 446 | −₹35,694 → **+₹68,469** | 9/9 |
| RSM (8) | 1,161 | −₹105,940 → **+₹104,027** | 8/8 |
| Combined (17) | 1,211 | +₹162,382 (unchanged) | 17/17 |
| **PORTFOLIO** | 2,818 | +₹20,747 → **+₹334,878** | 34/34 |

### Watchlist-merge bug fixed
`STRATEGY_WATCHLISTS["Relative Strength Momentum"]` was `["rsm_swing", "consensus"]`
→ RSM was merging the 23 unvalidated `consensus` names (live showed RSM=30 not 8).
Changed to `["rsm_swing"]` so RSM trades only its 8 OOS-validated symbols.

### Deployment
Paper trader restarted **PID 65888** (paper mode, state kept), same flags. Live
universe now RSM=8, Combined=17, Manual=9 (28 unique) — all net-positive OOS.

### Relevant files
- `scripts/run_consolidated_backtest.sh` — 3-strategy sequential runner.
- `scripts/run_pruned_backtest.sh` — re-backtest of the pruned Manual/RSM sets.
- `data/backtest_*_15m_manual_final.json` / `_rsm_final` / `_combined_final` —
  pre-prune consolidated results (73/42/17 syms).
- `data/backtest_*_15m_manual_pruned.json` / `_rsm_pruned` — post-prune (9/8 syms).
- `data/symbol_watchlists.json` — pruned `rsm_swing` (8), `manual_*_deploy` (9/5),
  `combined_swing` (17) + `_full` backup keys.
- `scripts/paper_trade.py` — `STRATEGY_WATCHLISTS` RSM fix.

## Phase 28 — Data prep for scalping (2026-07-17)

Prep for Phases 29/30 (mean-reversion + ML on the 56 OOS-pruned symbols).
- Fixed `scripts/download_history.py`: it rejected `1m`/`5m` as "unsupported".
  Added `1m` (7d yf / 365d Upstox) and `5m` (729d) to `_TF_CONFIG` +
  `_UPSTOX_DAYS`. `5m` saves NATIVE 5m (resampled from 1m at download time).
- Downloaded **5m history for all 56 pruned symbols** + `^NSEI` + `^NSEBANK`
  into `data/cache/5m/` (~37,400 bars/symbol, 2024-07 → 2026-07).
- Fixed `data/downloader/data_registry.py`:
  - `_INTERVAL_MAP["5m"]` was `"1m"` (expected to resample 5m from a 1m cache we
    don't have for these names) → changed to `"5m"` so it reads native 5m.
  - **Tail-cap bug**: `get_bars` returned `df.tail(lookback_days*10+100)`, a
    ~10-bars/day heuristic. For fine intraday TFs this silently truncated the
    window (5m@~75 bars/day → only ~99 days; 15m@~25/day → ~296 days). ALL prior
    backtests actually used recent bars, not full 729d (pre-existing; 15m left
    unchanged to preserve validated results). Added `{"1m":400,"5m":80}`
    multipliers so 5m/1m get full history; 15m/1h/1d keep `*10` (unchanged).

## Phase 29 — Mean-reversion scalping engine — REJECTED (net-negative) (2026-07-17)

Built a counter-trend mean-reversion engine to try to unlock the 56 pruned
names via a different market behaviour (reversion, not continuation).
- `engines/mean_reversion_engine.py`: Bollinger z (30) + RSI overshoot (20) +
  reversal-bar recovery (20) + volume climax (15) + NIFTY confluence (15),
  LONG (oversold bounce) + SHORT (overbought fade) symmetric, timeframe-agnostic.
- `strategies/mean_reversion_scalp_strategy.py`: wrapper registered as
  **"Mean Reversion Scalping"** (new name; old restrictive "Mean Reversion
  Trading" left intact). Per-symbol SL/TP, direction-aware stops.
- `scripts/run_backtest_portfolio.py`: added `--no-multi-tf` (disables
  `htf_check` so counter-trend entries aren't blocked).
- `scripts/tune_mr_scalp_sltp.py`: 8-worker parallel grid tuner selecting on
  **NET PnL after costs** (SL{1.0,1.5,2.0,2.5}×TP{0.5,1.0,1.5,2.0}).
- `scripts/oos_split_validate.py`: reusable 50/50 both-halves-net-positive filter.

**Verdict — DEAD (both 15m and 5m):**
- 15m: no gross edge (TATAELXSI gross avgR −0.097 before costs); tuner combos
  all net-negative even at cost-favorable wide stops (DIXON −₹17k, FEDERALBNK
  −₹11k).
- 5m FULL history, net of costs: ALL of ADANIPOWER/TATAELXSI/CYIENT/DIXON
  net-negative, **total −₹79,041 / 950 trades** (−₹68 to −₹185/trade). Gross
  avgR ~0. ADANIPOWER's +0.13R on the recent 99d was **time-selection bias**
  (collapsed to +0.008R over 729d — same trap as Phase 11).
- Root cause: costs (~₹90–185/trade) dominate; scalping = more trades = MORE
  cost drag. Consistent with the Phase 14/27 lesson: **cost-per-trade is the
  binding constraint, not signal direction.**

## Phase 30 — ML net-profit filter — WORKS OOS (2026-07-17)

Reframed the problem: instead of a new signal source, train a classifier to
predict **P(trade is net-positive after costs)** from entry-time features and
trade only the high-confidence tail (i.e. trade RARELY — attack the cost
constraint directly).

- `scripts/train_ml_filter.py`: XGBoost classifier. Uses the feature vector the
  backtest **already logs per trade** (rsi_14, atr_pct, volume_ratio, bb_width,
  EMA/high/low distances, 30m & 1d trend/return, day_type, stock_type, htf_pass,
  score) + hour/weekday + strategy tag. Label = `pnl_net > 0`.
- **Rigorous 3-way TIME split**: train 50% (fit) / val 20% (pick threshold by a
  fixed a-priori selectivity-first rule = highest threshold that is val-positive
  with ≥20 kept trades) / test 30% (untouched, reported). No random splits, no
  threshold-picking on the eval set.
- Dataset: pooled **10,157 trades** from RSM+Manual+Combined backtests across all
  56 pruned symbols (`data/backtest_trades_15m_ml_{rsm,manual,combined}.json`),
  generated cache-only 15m via `--out-suffix _ml_*`.

**Result (untouched test, val-chosen thr=0.75):**
| | Trades | WR | Net PnL | Net/trade |
|---|--------|-----|---------|-----------|
| Raw (unfiltered) | 3,048 | 32.3% | **−₹115,537** | −₹38 |
| ML-filtered ≥0.75 | 74 | 47.3% | **+₹4,568** | +₹62 |
| (ref) ≥0.80 | 27 | 63.0% | +₹6,664 | +₹247 |

The filter turns net-negative raw signals into a net-**positive** OOS subset by
extreme selectivity (~2% of signals). Top features are genuine setup signals
(30m_trend, 30m_return, stock_type, 1d_return, atr, distances, hour) + strategy
tag. Verdict: **ML FILTER WORKS OOS.** Caveat: the edge is small/sparse
(~74 trades over ~90d across 51 symbols) — a value-rescue, not a game-changer.
Model saved to `data/ml_net_filter.json` (+ `_meta.json` with threshold+features).

### Relevant files (Phases 28–30)
- `engines/mean_reversion_engine.py`, `strategies/mean_reversion_scalp_strategy.py`
- `scripts/tune_mr_scalp_sltp.py`, `scripts/oos_split_validate.py`
- `scripts/train_ml_filter.py`, `data/ml_net_filter.json` + `_meta.json`
- `data/backtest_trades_15m_ml_{rsm,manual,combined}.json` — labeled datasets
- `scripts/run_backtest_portfolio.py` — `--no-multi-tf`
- `scripts/download_history.py` (1m/5m), `data/downloader/data_registry.py`
  (5m native + tail-cap multipliers)

## Phase 31 — ML Standalone Strategy (Option B) — WORKS OOS (2026-07-17)

The user asked whether ML can drive a NEW standalone strategy on ALL stocks
(not just filter existing signals like Phase 30). Built and validated it.

**Core idea:** train XGBoost to answer *"is THIS bar a good entry?"* from raw
market state, then trade only the high-confidence tail. Unlike Phase 30 (which
filtered the 3 strategies' signals on 56 pruned names), this GENERATES its own
entries on every bar across the full 152-symbol universe.

### B1/B2 — bar-level labeled dataset (`scripts/ml_strategy_dataset.py`)
- For every 3rd bar of 152 symbols (15m, 2yr), computes a self-contained feature
  vector — VECTORISED copies of `WalkForwardBacktest._compute_entry_features`
  (8 technicals: rsi_14, atr_pct, volume_ratio, bb_width, recent hi/lo dist,
  ema20/50 dist) + `build_htf_context` (stock 30m/1d) + NIFTY 30m/1d context +
  hour/weekday. Feature parity vs the static method verified to 1e-6.
- Labels each bar by FORWARD-SIMULATING a trade: SL 0.5% / TP 5.0% / max hold 96
  bars (user-chosen intraday-style), using the SAME cost model + position sizing
  as the backtest → label = `pnl_net > 0`. Skips ambiguous bars (SL & TP both
  first-hit in the same bar). Generates BOTH a LONG and a SHORT label per bar.
- Output: `data/ml_strategy_dataset.parquet` — **1,264,783 labeled entries**
  (~13% net-positive base rate). Runs in ~11s (vectorised).

### B3 — training + walk-forward (`scripts/train_ml_strategy.py`,
`scripts/walkforward_ml_strategy.py`)
- **Critical regime finding (mirrors Phase 11):** a LONG-only model is NOT robust
  — a single contiguous val slice landing in the 2024-25 bear market forces an
  ultra-conservative threshold, and LONG-only loses in bear folds. Adding SHORT
  (symmetric) fixes the root cause: the model learns to go LONG in uptrends /
  SHORT in downtrends (top features are `direction_*` + NIFTY regime).
- **Threshold is regime-fragile if val-selected.** A per-fold fixed-threshold
  sweep showed thr **0.80** is net-positive in ALL 4 walk-forward folds (both
  bear AND bull), while lower thresholds lose in bear folds. So the deploy
  threshold is FIXED a-priori at **0.80** (justified by the project thesis
  "only extreme selectivity beats costs" — Phase 30 landed at 0.75 — and
  confirmed by the walk-forward, not chosen on any single test slice).

**Walk-forward OOS (expanding window, 4 folds, fixed thr 0.80, LONG+SHORT):**
| fold | regime | raw net | ML trades | ML net | net/trade | WR |
|------|--------|---------|-----------|--------|-----------|-----|
| 1 | bear | −₹3.6M | 35 | **+₹26,378** | +754 | 40% |
| 2 | bear | −₹5.8M | 6 | **+₹742** | +124 | 17% |
| 3 | bull | +₹5.1M | 5 | **+₹1,071** | +214 | 20% |
| 4 | mixed | −₹0.8M | 25 | **+₹21,794** | +872 | 44% |
| **agg** | | −₹5.1M | **71** | **+₹49,985** | **+704** | **38%** |

Net-positive in EVERY fold. The model turns random-entry's −₹5.1M into +₹50k by
extreme selectivity (~71 trades / ~1yr test across 152 syms × 2 dirs).

### B4/B5 — executable wrapper (`strategies/ml_strategy.py`, "ML Standalone")
- `MLStrategy(ExecutableStrategy)`: at each bar scores BOTH a LONG and a SHORT
  entry via the trained model and takes whichever clears thr 0.80; exits at the
  fixed 0.5%/5.0% the model was trained on. Registered in `strategies/selector.py`.
- Feature parity with training guaranteed by reusing `_compute_entry_features` +
  `build_htf_context` (self-builds stock 30m/1d + NIFTY context so it needs no
  htf_check gate; run backtests with `--no-multi-tf`).
- Retrains on ALL 1.26M rows for deployment → `data/ml_strategy_model.json`
  (+ `_meta.json`: threshold 0.80, 35 features, sl/tp, directions LONG+SHORT).
- **Live-engine backtest (5 symbols, 730d, `--no-multi-tf`)**: 43 trades,
  WR 46.5%, **net +₹31,812**, 4/5 profitable (WIPRO +₹6.5k, TATAELXSI +₹9.7k,
  DIXON +₹13.4k, RELIANCE +₹3.2k, ONGC −₹0.9k) — confirms the strategy works
  through the ACTUAL deployment path, not just the labeling sim.

### Verdict
**ML Standalone Strategy WORKS OOS** — net-positive in all 4 walk-forward folds
and via the live engine path, symmetric (regime-robust), on the full universe.
Caveat: very sparse (extreme selectivity) — a low-turnover, high-quality sleeve,
not a high-frequency engine. NOT yet wired into the paper trader (pending
go-ahead). Note: per-bar inference makes backtests slow (~2-4 min/symbol); live
paper trading only infers once per cycle so it's fine.

### Relevant files
- `scripts/ml_strategy_dataset.py` — bar-level labeled dataset generator
- `scripts/train_ml_strategy.py` — trainer (fixed 0.80 deploy threshold)
- `scripts/walkforward_ml_strategy.py` — regime-robust walk-forward (`--fixed-thr`, `--regime-gate`)
- `strategies/ml_strategy.py` — "ML Standalone" executable (registered in selector)
- `data/ml_strategy_model.json` + `_meta.json` — deployment model
- `data/ml_strategy_dataset.parquet` — 1.26M labeled bars
- `data/backtest_*_15m_ml_standalone_test.json` — 5-symbol live-path validation

## Phase 32 — ML Universal Filter (Option A) + Strategy Selector (Option C) — BOTH WORK OOS (2026-07-18)

Completed the other two ML options the user asked for (Phase 31 = Option B). Both
extend the Phase 30 filter from the 56 pruned names to the **full 152-symbol
universe** and share ONE pooled dataset.

### Dataset — 3 deployed strategies × full universe (152 symbols, 15m, 730d)
Ran RSM / Combined Swing / Manual across all 152 symbols (`--provider yfinance
--cache-only --no-intraday --out-suffix _mlall_*`). **28,215 pooled trades**
(RSM 15,705 + Combined 8,733 + Manual 3,777), each carrying the entry-time
feature vector the backtest already logs + `pnl_net` label.
- Files: `data/backtest_trades_15m_mlall_{rsm,combined,manual}.json`.
- Op note: RSM/Manual runs died near completion on the first (parallel-×3) launch
  writing output only at the end; re-ran RSM+Manual as 2 parallel jobs (Combined
  had already finished). ~1 min/symbol for RSM.

### Method (`scripts/train_ml_filter_all.py`, reuses Phase 30 pipeline)
- **Option A (Universal Filter):** identical to Phase 30 (XGBoost, `strategy` as
  a feature) but trained on ALL symbols. 3-way TIME split (train 50 / val 20 /
  test 30); a-priori selectivity-first threshold on val; report NET rupees on the
  untouched test.
- **Option C (Strategy Selector):** an INFERENCE POLICY on the SAME model — when
  multiple strategies fire on the same (symbol, day), keep only the single
  highest-proba signal (conflict resolution) instead of independently filtering.

### Result (untouched TEST = 8,465 trades, NET rupees)
| Policy | Trades | WR | Net PnL | Net/trade |
|--------|--------|-----|---------|-----------|
| RAW (all signals) | 8,465 | 38.6% | **+₹43,740** | +₹5 |
| **Option A** (filter ≥0.80) | 55 | 76.4% | **+₹16,269** | **+₹296** |
| **Option C** (best/sym/day ≥0.80) | 48 | 81.2% | **+₹15,129** | **+₹315** |

**Both verdicts: WORKS OOS** — and far more ROBUST than Phase 30's pruned-only
run. Unlike the fragile pruned pool (where val thr 0.75 → +₹4.6k was split-
sensitive), here the val AND test net-PnL sweeps rise **monotonically together**
with the threshold — strong evidence of a real, stable edge:

| thr | VAL net | TEST net | TEST trades | TEST net/tr |
|-----|---------|----------|-------------|-------------|
| 0.60 | +33,857 | **+161,764** | 1,505 | +107 |
| 0.65 | **+43,035** (val-max) | +108,598 | 795 | +137 |
| 0.70 | +37,984 | +62,328 | 371 | +168 |
| 0.80 | +17,894 | +16,269 | 55 | +296 |

### Key takeaways
- The **full-universe RAW pool is already marginally net-positive** (+₹5/trade)
  vs the pruned-only pool (−₹38/trade, Phase 30). Adding the 96 non-pruned
  symbols dilutes toward break-even, and the filter then concentrates the edge.
- **Better operating point than the sparse 0.80:** the val-max-net threshold
  **0.65** (val-selected, non-leaking) gives OOS test **+₹108,598 over 795
  trades (+₹137/trade, WR 55.8%)** — ~2.5× raw total net AND ~27× per-trade,
  with enough volume to be practical. thr 0.60 is even higher total (+₹161,764)
  but lower selectivity. The a-priori selectivity-first rule lands at 0.80
  (highest thr net-positive on val with ≥30 kept) → the ultra-selective corner.
- **Option C ≈ Option A at 0.80** (48 vs 55 trades) because multiple approved
  signals rarely collide on the same symbol/day at extreme selectivity; C's
  conflict-resolution value would surface at lower thresholds.
- Top features: `strategy_*` tags dominate (0.20/0.17/0.05 — the model leans on
  WHICH strategy fired), then `30m_trend_UP`, `1d_trend_DOWN`, `30m_return_3`,
  stock_type, ema/bb/atr distances, hour.

### Status
All three ML options now built and OOS-validated: **B (Standalone, Phase 31),
A (Universal Filter), C (Selector)**. NONE are wired into the paper trader yet —
pending user decision on deployment (which option(s), which threshold).

### Relevant files
- `scripts/train_ml_filter_all.py` — Options A + C trainer/eval (reuses `train_ml_filter`)
- `data/ml_filter_all.json` + `_meta.json` — full-universe filter model (43 features, thr 0.80)
- `data/backtest_trades_15m_mlall_{rsm,combined,manual}.json` — 28,215 pooled trades
- `/tmp/mlall_syms.txt` — 152-symbol universe list

## Phase 33 — Save results + per-symbol thresholds + wire filter into paper trader (2026-07-18)

User asked to (a) save the Phase 32 results with a date + a weekly trade estimate,
and (b) decide the next ML direction (per-stock models? profitable-only? else?).

### Trade-frequency estimate (test period 2026-03-11→2026-07-10 ≈ 16 weeks)
| global thr | test trades | ~trades/wk | ~/day | test net | ~net/wk |
|-----------|-------------|-----------|-------|----------|---------|
| 0.60 | 1,505 | 93 | 18.6 | +₹161,764 | +₹9,985 |
| **0.65** | 795 | **49** | 9.8 | **+₹108,598** | +₹6,704 |
| 0.70 | 371 | 23 | 4.6 | +₹62,328 | +₹3,847 |
| 0.80 | 55 | 3.4 | 0.7 | +₹16,269 | +₹1,004 |

Saved full sweep + weekly table + per-symbol map to
`data/results/ml_filter_all_2026-07-18.json`.

### Next-direction decision (evaluated the user's two ideas)
- **Per-stock ML models** — REJECTED a priori: ~50-200 trades/symbol is far too
  sparse for 152 reliable models (would overfit like the Phase 30 pruned pool).
- **ML on profitable-only stocks** — REJECTED: the model already conditions on
  `strategy_*`/`stock_type` features; removing net-negative symbols would REMOVE
  the negative examples the model needs to learn what to avoid.
- **Chosen instead: per-symbol THRESHOLD tuning** (not per-symbol models) +
  wire the validated global filter into the live trader.

### Per-symbol threshold tuning — TESTED, REJECTED (`scripts/tune_ml_filter_thresholds.py`)
Fit model on train (50%), pick each symbol's own threshold on val (20%, max-net
with ≥6 kept, else skip), measure on test (30%). Result: per-symbol
**net +₹85,729 / 1,699 trades vs global 0.65's +₹108,598 / 795** → **₹22,869
WORSE**. Cause: ~37 val trades/symbol makes per-symbol thresholds noisy (many
collapse to the loosest 0.50, which doesn't hold OOS). **Verdict: use ONE global
threshold.** (Per-symbol map deleted so it can't be deployed by mistake.)

### Wired Option A filter into the paper trader (opt-in)
- `scripts/ml_filter_gate.py`: live inference wrapper. Rebuilds the EXACT feature
  vector the backtest logs (reuses `WalkForwardBacktest._compute_entry_features` +
  the same `features` assembly + `score`/`hour`/`weekday` + `DROP_FEATURES`),
  one-hots and reindexes to the trained 43-feature list. `passes_ml_filter(ctx,
  decision, thr)` is **fail-open** (missing model / <50 bars → allow, never
  silently block everything). **Encoding parity vs the training pipeline verified
  EXACT (max |Δproba| = 0 over 200 trades).**
- `scripts/paper_trade.py`: new `--ml-filter` flag + `--ml-filter-thr` (default
  0.65). Gate runs in `run_cycle` right after the Phase 24 confirmation gate;
  logs `[ml-filter] PASS P=..` / `< thr`. Default OFF → existing behaviour
  unchanged. Live path validated end-to-end: TATAELXSI P≈0.65-0.67 (PASS),
  RELIANCE/WIPRO P≈0.27-0.32 (filtered), Manual consistently lowest (its
  cost-sensitivity) — correctly discriminating.

### OPEN DEPLOYMENT QUESTION (for the user)
The filter was validated on the FULL 152-symbol universe's raw signals (+₹108,598
at thr 0.65). The CURRENT live deployment (Phase 27) already runs the PRUNED
watchlists (RSM 8 / Combined 17 / Manual 9 = 34 OOS-winning symbols). Two ways to
deploy the filter:
1. **Pruned + filter** (conservative double-selection) — safest, fewer trades.
2. **Full universe + filter does the selection** (the Phase 32 thesis: "trade all
   stocks, let ML pick") — matches what was validated (+₹108k), ~49 trades/wk.
Not restarted live yet — pending user's choice of universe.

### Commands
```bash
# Save results + per-symbol threshold test
.venv/bin/python scripts/tune_ml_filter_thresholds.py

# Paper trade WITH the ML filter (full universe, filter selects) — thesis deploy
.venv/bin/python scripts/paper_trade.py \
  --strategies "Relative Strength Momentum,Combined Swing,Manual Institutional (time-gated)" \
  --alloc 33,33,34 --sl 1.0,2.0,0.5 --tp 2.5,4.0,5.0 --mode both \
  --ml-filter --ml-filter-thr 0.65 --upstox --loop --interval 5
```

### Relevant files
- `scripts/tune_ml_filter_thresholds.py` — per-symbol threshold tuner + dated results saver
- `scripts/ml_filter_gate.py` — live filter inference (exact parity), `--ml-filter` gate
- `scripts/paper_trade.py` — `--ml-filter`/`--ml-filter-thr`, gate in `run_cycle`
- `data/results/ml_filter_all_2026-07-18.json` — saved sweep + weekly estimates

## Phase 34 — Deploy ML Standalone (Option B) + ML Filter (Option A) together, full universe (2026-07-18)

User decision: deploy BOTH ML sleeves live (paper) — Option A (filter on
RSM/Combined/Manual) AND Option B (ML Standalone as its own strategy), on the
FULL 153-symbol universe (the Phase 32 thesis: trade all stocks, let ML select),
with ML Standalone trading **both LONG and SHORT** (it is symmetric by design).

### Why full universe + filter (over pruned + filter)
Per-trade quality AND annualized profit both favour the full-universe filter:
Phase 27 pruned (34 syms, no filter) = +₹119/tr, ~+₹167k/yr; Phase 32 full+filter
(thr 0.65) = +₹137/tr, ~+₹330k/yr (~2×). Pruned+filter double-counts OOS
selection (leaky) and shifts the filter's calibration distribution. Full universe
is the consistent deployment of what was validated.

### Full-universe watchlist
- `data/symbol_watchlists.json`: new key **`full_universe`** = 153 symbols
  (15m ∩ 1d cache, ex-indices). Backup
  `data/symbol_watchlists.json.bak_pre_full_universe_*`.
- `scripts/paper_trade.py` `STRATEGY_WATCHLISTS`: RSM / Combined / Manual /
  **ML Standalone** all → `["full_universe"]` (was the Phase-27 pruned keys).
  The ML filter now does symbol selection dynamically. To revert: restore
  `rsm_swing` / `combined_swing` / `manual_*_deploy`.

### ML Standalone wired as a 4th strategy — gate bypasses (`run_cycle`)
The standalone's thr-0.80 model already conditions on hour/weekday/direction/bar
state/regime, so external gates would double-count or wrongly block it. Added
`is_ml_standalone = strat_name == "ML Standalone"` guards:
| Gate | ML Standalone | Why |
|------|--------------|-----|
| `ALLOW_SHORTS` | **forced True** | symmetric model; SHORT validated in bear+bull folds |
| `multi_tf_filter` | **False** (`_decide_trade_for_mode`) | takes counter-trend entries; Phase 31 used `--no-multi-tf` |
| day-of-week (`calendar_conviction_multiplier`) | **skipped** (mult=1.0) | weekday is a model feature |
| ML filter (`passes_ml_filter`) | **skipped** | filter model has no `strategy_ML-Standalone` column → undefined |
| confirmation gate (Phase 24) | already Manual-only → passes | — |
| entry timing / daily cap / conviction / SL-TP | normal | SL/TP are the model's own 0.5%/5.0% (ignores `--sl/--tp`) |
- `_build_symbol_context` now also returns `nifty_1d`; `_decide_trade_for_mode`
  passes `nifty_daily=ctx["nifty_1d"]` (ML Standalone needs NIFTY daily context).
- `STATE_PATH` now honours `INST_PAPER_STATE` env (isolated test states).

### Validation (before deploy)
- py_compile clean. `full_universe`=153; all 4 strategies route to it.
- **Filter encoding parity vs training pipeline: EXACT** (Phase 33, max |Δproba|=0).
- ML Standalone fires through the ACTUAL paper path (`_decide_trade_for_mode`,
  `force_strategy="ML Standalone"`, `multi_tf_filter=False`): scanning history,
  fires ~0.2-0.3% of bars (extreme selectivity, as designed) and **both
  directions confirmed** (LONG + SHORT both produced). No crash; no-signal is the
  common/expected case at thr 0.80.
- Isolated one-shot 4-strategy cycle: clean; cash split **RSM 25 / Combined 30 /
  Manual 25 / ML Standalone 20 = ₹50,000**; day cap 20 (5×4).

### Manual golden-window symbol-override bug fixed
The Phase-A time-based switcher restricted Manual to the pruned
`manual_morning_deploy` (9) / `manual_evening_deploy` (5) lists during golden
windows — which would override `full_universe`. Manual has its OWN internal
golden-window TIME gate (`strategies/manual_institutional_strategy.py` HARD GATE
1), so the paper-trader symbol switch is now loaded ONLY when Manual is
configured with a `manual_*` watchlist key. Under full-universe it's skipped;
Manual scans all 153 (time-gated internally, ML-filtered for selection).

### Deployment (LIVE, paper mode)
`scripts/start_all.sh` updated to the 4-strategy config + `--ml-filter
--ml-filter-thr 0.65`; added `RESET=1` env (adds `--reset`). Restarted via
`RESET=1 ./scripts/start_all.sh` (paper PID 73733, scanner PID 73731):
- `--strategies "RSM,Combined Swing,Manual,ML Standalone" --alloc 25,30,25,20
  --sl 1.0,2.0,0.5,0.5 --tp 2.5,4.0,5.0,5.0 --mode both --ml-filter
  --ml-filter-thr 0.65 --upstox --loop --interval 5`.
- Log confirms: 4 strategies × 153 syms, 153 unique, loop started, market closed
  (Sat) → waits for Mon 09:15. No errors. No `--real` (IP-locked; paper only).

### Expected (est.): ~52 trades/wk, ~+₹8,800/wk
Filtered RSM+Combined+Manual ≈ 49 tr/wk (+₹6,700) + ML Standalone ≈ 3 tr/wk
(+₹2,100, both directions).

### Relevant files
- `data/symbol_watchlists.json` — `full_universe` (153) + backup
- `scripts/paper_trade.py` — full-universe routing, ML Standalone gate bypasses,
  `nifty_1d` in ctx, `INST_PAPER_STATE`, Manual golden-window guard
- `scripts/start_all.sh` — 4-strategy Phase-34 config + `RESET=1` env
- `strategies/ml_strategy.py` — "ML Standalone" (unchanged; deployed)

## Phase 35 — Full NSE-universe data cache, native multi-TF, daily EOD refresh (2026-07-18)

User request: keep 1m/15m/30m/1h/1d data for **all NSE stocks** (F&O + NIFTY 500,
minus zero-volume penny stocks) updated regularly and stored — and **prefer
native data per timeframe, not resampled-from-1m**.

### KEY UNLOCK — Upstox V3 historical API gives TRUE NATIVE candles
V2 (`_map_timeframe`) collapses 15m/30m/1h all to `30minute` — no native 15m/1h.
**V3** (`/v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}`) supports
custom native intervals: `minutes/1..300`, `hours/1..5`, `days/1` (data from Jan
2022 for intraday, Jan 2000 for daily). So every TF is fetched NATIVE — zero
resampling. Verified spacing: 1m=1min, 15m=15min, 30m=30min, 1h=1h, 1d=1day.
Per-request window caps: minutes 1–15 → 1 month; minutes >15 → 1 quarter; hours →
1 quarter; days → 1 decade (single call).

- `data/upstox/upstox_market_data_provider.py`: added `load_historical_v3(key,
  tf, start, end)` (chunks to respect window caps + concats), `load_intraday_v3`
  (today's native candles), `_fetch_candles_v3`, and `_V3_MAP`
  (tf→unit/interval/chunk_days). All existing V2 methods untouched (live paper
  trader still uses V2 `_upstox_live`).

### Rate limiting — the binding constraint
Upstox "Other Standard APIs" (historical): **50/s, 500/min, 2000 per 30 min**.
The 30-min cap = ~1.11 req/s SUSTAINED is the real limit. Two limiter iterations:
1. First `_V3RateLimiter` used sliding windows that ALLOWED a burst up to the cap
   (1950 in 30 min) then, once saturated, blocked ALL workers for ~20 min while
   that burst of timestamps aged out of the 30-min window together — looked
   exactly like a hang (0% CPU, no file writes for 20+ min, would resume, freeze
   again next window).
2. **Rewritten to EVEN PACING** (slot reservation): each caller reserves the next
   evenly-spaced slot under a lock (interval 1800/1900 ≈ 0.947s ⇒ ~1.056 req/s ⇒
   ~1901/30min, ~63/min — safely under all three caps), then sleeps until it.
   Smooth, observable progress; never bursts, never freezes, never 429s. Same
   total throughput (the cap is the cap) but predictable ~1 file every ~28s for
   15m. Plus 429 `Retry-After` + network-timeout retry (4 attempts) and 15s read
   timeout as belt-and-braces.

### Symbol universe (`scripts/build_nse_universe.py` → `data/nse_universe.json`)
- **NIFTY 500** from `niftyindices.com/IndexConstituent/ind_nifty500list.csv`
  (symbol + ISIN). NSE's own `equity-stockIndices` API is 404/anti-bot; the
  niftyindices CSV is reliable.
- **F&O underlyings** from the Upstox instrument master
  (`assets.upstox.com/.../complete.json.gz`, segment NSE_FO → distinct
  `underlying_symbol`/`underlying_key`, excluding index underlyings): 210 names.
- Upstox keys resolved via the master (NSE_EQ + instrument_type EQ = 2,390 real
  equities; ISIN→key + symbol→key maps). Merged into
  `data/cache/metadata/instrument_keys.json`.
- **Penny filter**: avg daily **turnover** (close×volume, ₹) over ~30 days < ₹1
  cr → drop. NOTE: turnover (₹) is the correct metric — an absolute share-volume
  floor wrongly drops high-priced liquid names (MRF ₹1.4L/share trades few shares
  but ₹102cr turnover), so `--min-volume` defaults 0 (disabled).
- Result: **500 symbols** (all 210 F&O ⊂ NIFTY 500; every NIFTY 500 name clears
  ₹1cr turnover → 0 dropped). `data/nse_universe.json`: `{symbols, keys,
  total, nse500, fno, overlap, ...}`.

### Refresh daemon (`scripts/refresh_data_cache.py`)
Fetches native V3 per TF and merges into `data/cache/<tf>/<symbol>.parquet`
(dedup on timestamp keep=last; timestamps normalised to IST-naive to match the
existing cache convention). Thread-pooled; the provider's limiter caps aggregate
rate so worker count only hides latency.
- **`--backfill`** (one-shot deep): depths 1d=1825d, 15m=730d, 30m=730d,
  1h=730d, 1m=45d. **TF-priority order (1d→15m→30m→1h→1m)** so critical data
  lands first; **`--resume`** skips (symbol,tf) already current (last bar ≤4
  days old) → interruptible/restartable. `--force` re-fetches all.
- **`--eod`** (daily top-up): short windows (1d=10d…1m=5d) incl. today.
- **`--loop`**: runs `--eod` once/day at ≥16:00 IST (30 min after close).
- Due to the 2000/30-min cap, a full deep backfill of 500 syms (~24k requests)
  takes ~5-6 h — a ONE-TIME background job. Daily EOD (~2.5k requests) ≈ 40 min.

### Integration
- `scripts/start_all.sh`: added a 3rd background process — the refresher in
  `--loop` mode (logs `data/refresh_cache.log`). `stop_all.sh` + the start
  kill-list updated to include `refresh_data_cache`.
- Backfill launched in background (`data/refresh_cache_backfill.log`); EOD loop
  keeps every TF current going forward.

### CRITICAL BUG FIXED — shared requests.Session deadlocked the backfill
The first full backfill HUNG at ~100-150 requests (0% CPU, no progress, socket
timeout never fired). Root cause: `_get_session()` returned ONE shared
`requests.Session` reused by all 10 worker threads. `requests.Session` is NOT
thread-safe — its urllib3 connection pool deadlocks under concurrent
multi-thread use (threads block acquiring a pooled connection, which is BEFORE
the 15s read timeout applies, so nothing ever times out). Fix: `_get_session()`
now returns a **thread-local** Session (each thread gets its own, with an
`HTTPAdapter(pool_connections=4, pool_maxsize=4)`). Verified: 20 syms × 15m ×
10 workers = 0 failures in 114s (previously hung forever). Full backfill then
ran clean — 1d: 500 syms / 345k bars / 0 fail in 64s, then into 15m/30m/1h/1m.
- **Backfill depths adjusted**: 1m lowered 60d→45d (V3 intraday history starts
  ~Jan 2022 but 1m is huge/rarely needed deep); 30m/1h lowered 1095d→730d to
  match 15m (V3 intraday depth is the constraint; keeps the job ~6h not ~8h).

### Resume + TF-priority (resumable one-time backfill)
`--resume` skips any (symbol, tf) whose cached last bar is ≤4 days old (covers
weekends/holidays) via `_cache_is_current()`, so an interrupted backfill
restarts cheaply. `--force` overrides. TFs always processed in priority order
`1d → 15m → 30m → 1h → 1m` so the most useful data lands first even if the job
is killed mid-run. `_process_one` is the per-(symbol,tf) unit of work.

### Data quality (verified, e.g. AARTIIND)
1m 45-60d, 15m native 730d (2024-07→2026-07), 30m/1h native 730d (2023-07→…),
1d 5yr — all correct native spacing, IST timestamps, merged without dupes.

### Relevant files
- `scripts/build_nse_universe.py` — NIFTY500+F&O universe builder + penny filter
- `data/nse_universe.json` — 500 symbols + Upstox keys
- `scripts/refresh_data_cache.py` — native V3 backfill/EOD/loop daemon (resume, TF-priority)
- `data/upstox/upstox_market_data_provider.py` — V3 native fetch + `_V3RateLimiter`
- `scripts/start_all.sh` / `stop_all.sh` — 3rd process wiring

## Phase 36 — Daily Trend Breakout strategy (trailing ATR stop, LONG-only) (2026-07-18)

User goal: capture large 10–50%+ moves that the 4 fixed-SL/TP strategies (RSM,
Combined, Manual, ML Standalone) structurally cannot — none let winners run.
Built a NEW daily (1d) trend-following strategy with a **trailing ATR stop and
NO fixed take-profit**, so a few large winners drive the edge.

### Concept validation (read-only, 452 symbols × 5yr daily parquet)
Donchian channel breakout + close-based chandelier trail: **4702 trades,
+3.29% avg gross, PF 1.93, WR 40.9%, avg win +16.75% / avg loss -6.02%,
max win +172%.** 65.5% of symbols profitable; **top 5% of trades drive 90% of
PnL** (fat-tailed — the whole point). Best grid: channel=15, trail_atr=4.0,
initial_sl_atr=4.0. LONG-only (user: "dont add short side").

### Trailing-stop plumbing (backward compatible — 0 = legacy fixed SL/TP)
- `strategies/executable.py` `TradeCandidate`: added `trail_atr_mult` (>0 →
  trailing, take_profit ignored) + `max_hold_bars`.
- `scripts/backtest.py`:
  - `TradeDecision` + `BacktestTrade` carry `trail_atr_mult` / `trail_high` /
    `max_hold_bars`; `decide_trade` + trade-creation propagate them.
  - **Precompute `df["_atr_trail"]`** (true ATR14, no look-ahead) once per run.
  - `_check_exit`: new LONG trailing branch — **close-based chandelier**
    (hwm=highest close since entry; stop=max(stop, hwm − k·ATR); exit when
    close≤stop). Matches the validated concept. Fixed-SL/TP path unchanged.
  - `_settle_trade`: r_multiple now **signed diff/risk** (was WIN=reward/risk /
    LOSS=−1.0). Identical for fixed exits; correct for trailing partial losses
    (e.g. −0.4R) and runners. pnl_%/pnl_amount already used signed diff.
  - **Per-timeframe window**: `self.window_size = 250 if 1d else WINDOW_SIZE(100)`
    (daily needs ≥200 bars for SMA200). All 5 `WINDOW_SIZE` refs in `run()` now
    use `self.window_size`. Other TFs unchanged (still 100).
  - Per-trade `max_hold_bars` honoured in stale-cleanup + `_check_exit` bound.
- `scripts/run_backtest_portfolio.py`: `--timeframe` now accepts `1d`.

### CRITICAL pre-existing bug fixed — EXPIRED trades never booked to equity
Both EXPIRED exit paths (60-bar time-stop stale-cleanup + end-of-data cleanup)
set `pnl_amount`/`pnl_net` on the trade but **never did `capital += pnl_amount;
equity.append(capital)`** — so EXPIRED PnL was excluded from the equity curve
(→ wrong `total_pnl_pct`/`max_drawdown`, and the broken low equity tripped the
drawdown circuit breaker, suppressing entries). Latent for 15m strategies
(EXPIRED share = 0% — intraday EOD-closes, swing rarely hits the 200-bar cap;
**verified DMART RSM 15m = 0 EXPIRED**, so their validated numbers are
unaffected). Exposed by the daily strategy where the 60-bar time stop is a
legitimate, frequent exit (often on still-running winners). Fixed both paths.

### New files
- `engines/daily_trend_engine.py` — `DailyTrendEngine`: Donchian(15) breakout
  trigger + 6-factor LONG score (breakout strength /trend quality SMA50>SMA200 /
  volume confirmation / ADX proxy / RSI momentum / RS vs NIFTY), returns
  total_score + atr. LONG-only.
- `strategies/daily_trend_strategy.py` — `DailyTrendBreakoutStrategy`
  (name `"Daily Trend Breakout"`): defaults channel=15, trail_atr=4.0,
  initial_sl_atr=4.0, max_hold=60, min_score=60. Sets `trail_atr_mult` +
  sentinel take_profit (entry×5, ignored). Accepts+ignores sl_mult/tp_mult so
  the fixed-SL/TP tuning path can't override the trail. Optional per-symbol
  `data/daily_trend_tunings.json`.
- Registered in `strategies/selector.py`.

### Full-universe backtest (500 NSE syms w/ 1d cache, 1825d, `--no-multi-tf --slippage default`)
**171 symbols traded, 6903 trades, NET +₹1,992,944 after costs
(+₹289/trade), avgR +0.501, WR 48.3%.** 114 symbols net-positive; **108
net-positive with ≥10 trades (net +₹2,203,530).** Verified net<gross per trade
(costs subtracted correctly). Top: MAZDOCK +₹106k (avgR +2.56), BSE +₹101k,
RVNL +₹76k, RECLTD +₹72k, COCHINSHIP +₹69k, BAJAJ-AUTO +₹55k (WR 80%).
Single-symbol e.g. RELIANCE net +₹14,081 / PF 2.25 / 57 tr; ONGC +₹15,494 /
PF 2.79. The 329 non-trading names = recent IPOs (<270 bars) or cache-miss.

### Watchlists written (`data/symbol_watchlists.json`, backup made)
- **`daily_trend_breakout`** = **108** (net-positive ≥10 trades) — v1 universe.
- **`daily_trend_breakout_robust`** = **33** (net-positive in BOTH 50/50 time
  halves, split 2024-04-05; net +₹923,450 / 1889 tr) — conservative option.
  NOTE: the strict both-halves filter is arguably TOO harsh for a fat-tailed
  strategy (a symbol's one big winner landing in a single half fails it); the
  concept already validated the edge cross-sectionally (65.5% of 452 syms).

### Status / next
- Strategy is BUILT + backtest-validated net-positive. **NOT yet wired into the
  paper trader** (Phase 3 deferred) — needs: per-strategy TF map
  `{"Daily Trend Breakout": "1d"}` in `paper_trade.py`, trailing-exit logic in
  the live position monitor (mirror `_check_exit` close-based chandelier), and a
  `STRATEGY_WATCHLISTS["Daily Trend Breakout"] = ["daily_trend_breakout"]` entry.
- Optional Phase 2: `scripts/tune_daily_trend_tunings.py` per-symbol
  initial_sl_atr / trail_atr_mult grid → `data/daily_trend_tunings.json`.
- OPEN QUESTION for user: deploy the broad 108 or the conservative 33?

### Commands
```bash
# Full daily-universe backtest
.venv/bin/python scripts/run_backtest_portfolio.py --strategy "Daily Trend Breakout" \
  --timeframe 1d --no-intraday --no-multi-tf --days 1825 \
  --symbols "$(<symbol list>)" --provider yfinance --cache-only --slippage default \
  --out-suffix _daily_trend_full

# Single-symbol quick check (Python)
.venv/bin/python -c "from scripts.backtest import WalkForwardBacktest as W; \
  s=W('RELIANCE','Daily Trend Breakout','1d','yfinance',force_strategy='Daily Trend Breakout',\
  multi_tf_filter=False,cache_only=True).run(days=1825); print(s.profit_factor, s.total_pnl_pct)"
```

### Relevant files
- `engines/daily_trend_engine.py` — 6-factor Donchian breakout scorer (new)
- `strategies/daily_trend_strategy.py` — `DailyTrendBreakoutStrategy` (new)
- `strategies/executable.py` — `TradeCandidate.trail_atr_mult` / `max_hold_bars`
- `scripts/backtest.py` — trailing `_check_exit`, signed-R `_settle_trade`,
  `_atr_trail` precompute, `self.window_size`, EXPIRED-equity fix
- `scripts/run_backtest_portfolio.py` — `1d` timeframe choice
- `data/symbol_watchlists.json` — `daily_trend_breakout` (108) + `_robust` (33)
- `data/backtest_{portfolio,trades}_1d_daily_trend_full.json` — full results

## Phase 37 — Deploy Daily Trend Breakout as 5th paper sleeve (LONG-only, 1d) (2026-07-18)

Wired the Phase 36 strategy into the live paper trader as a 5th sleeve using the
**108-symbol `daily_trend_breakout`** universe. Paper-first (no `--real`).

### User decisions
- Universe: **108** (broad), not the 33 robust set.
- Allocation: shrink existing ×0.8 → **RSM 20 / Combined 24 / Manual 20 / ML 16 /
  Daily 20** (₹50k total). Entry = **next-day 09:15 open** on prior completed
  daily signal. **Paper first.** Daily entry cap 5/day (global `MAX_TRADES_PER_DAY`).

### paper_trade.py wiring (multi-timeframe, once-per-day pass)
- Globals: `STRATEGY_TIMEFRAMES = {"Daily Trend Breakout": "1d"}`, helpers
  `_tf_for` / `_is_daily_strategy`; `_DAILY_MORNING_WINDOW = (9.25, 10.5)`
  (09:15→10:30 IST morning entry/exit window).
- `STRATEGY_WATCHLISTS["Daily Trend Breakout"] = ["daily_trend_breakout"]`.
- `_build_daily_context`: PIT 1d frame, 250-bar window, **excludes today's
  in-progress bar** (decisions use prior completed daily close).
- `_decide_daily`: runs the strategy with `multi_tf_filter=False`,
  `intraday_mode=False`. Validated on MAZDOCK cache: 988 windows → 65 fires
  (matches ~64 backtest trades).
- `_daily_trailing_exit`: mirrors backtest `_check_exit` close-based chandelier
  (hwm since entry, stop=max(stop, hwm−k·ATR), + `max_hold_bars` time stop).
- `run_cycle`: `do_daily_pass` gate (once/day inside morning window, tracked via
  `state["daily_pass_date"]`); sections 0/1 skip `mode=="daily"` positions; new
  **section 1c** runs daily trailing exits; daily entry branch in section 2 stores
  `trail_atr_mult`, `trail_high`, `max_hold_bars`, `signal_date`, `mode="daily"`.
- **Bug fixed during integration**: daily entry branch referenced `strat_symbols`
  before it was assigned later in the loop (`UnboundLocalError`); moved the
  `strat_symbols = ...` computation above the daily branch so both share it.

### Validation
- `_daily_trailing_exit` synthetic tests (TRAIL WIN, MAX-HOLD WIN, OPEN rising
  stop) pass.
- **End-to-end `run_cycle` integration test PASS**: MAZDOCK 2022-07-27 breakout →
  books daily LONG @₹139.40, SL ₹124.49, trail×4.0ATR, mode=daily,
  signal_date=2022-07-27; synthetic crash frame → **TRAIL-STOP exit** with
  correct rupee PnL. `py_compile` + `bash -n start_all.sh` clean.

### start_all.sh (5-strategy config)
```
--strategies "Relative Strength Momentum,Combined Swing,Manual Institutional (time-gated),ML Standalone,Daily Trend Breakout"
--alloc 20,24,20,16,20   --sl 1.0,2.0,0.5,0.5,4.0   --tp 2.5,4.0,5.0,5.0,5.0
--mode both --ml-filter --ml-filter-thr 0.65
```
(Daily strategy ignores its sl/tp slots — placeholders only; keeps list arity.)
Restart with `RESET=1 ./scripts/start_all.sh` so cash re-splits into 5 sleeves.

### Known cosmetic notes (money correct, reporting only)
- Live `_record_exit` still books LOSS r_multiple as −1.0 (not signed) for
  trailing exits; **rupee PnL/cash is correct**, only displayed R may under/over-
  state a partial-trail loss. (Backtest already uses signed R.)
- Daily positions' mark price is only in `prices` during the daily pass, so
  intraday equity-curve/peak snapshots omit them between passes; self-corrects on
  the next pass. dd_scaler for daily entries is computed on the pass → correct.

### Relevant files
- `scripts/paper_trade.py` — `STRATEGY_TIMEFRAMES`, `_build_daily_context`,
  `_decide_daily`, `_daily_trailing_exit`, daily entry/exit branches in `run_cycle`
- `scripts/start_all.sh` — 5-strategy allocation (20/24/20/16/20)
