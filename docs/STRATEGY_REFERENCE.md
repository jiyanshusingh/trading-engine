# Strategy Reference — Institutional Trading AI

## Overview

Six strategies are deployed in the live paper trader (Upstox, ₹50k capital),
each with its own engine, watchlist, allocation, and entry/exit rules.
All share the same paper-trader infrastructure (`scripts/paper_trade.py`)
and the same cost model (STT 0.025%, brokerage ₹20, slippage 0.05%, GST 18%
on brokerage, NSE/SEBI exchange fees).

### Architecture

```
paper_trade.py (--loop --interval 5)
├── RSM Swing             (15m swing,  8 syms, alloc 18%)
├── Combined Swing        (15m swing, 17 syms, alloc 22%)
├── Manual Institutional  (15m intra,  9+5 syms, alloc 18%)
├── ML Standalone         (15m swing, 153 syms, alloc 14%)
├── Daily Trend Breakout  (1d swing,  108 syms, alloc 18%)
└── ML Opening Breakout   (5m intra,  500 syms, alloc 10%)
```

Each cycle (~5 min during market hours), the paper trader:
1. Fetches live bars (Upstox V2/V3 REST + intraday candles)
2. Merges today's intraday bars atop historical cache
3. Runs each strategy's `run()` → gets signals
4. Applies per-strategy gates (day-of-week, confirmation, ML filter)
5. Opens positions (paper or real `--real` orders)
6. Monitors existing positions (SL/TP/trailing/EOD)

---

## 1. Relative Strength Momentum (RSM Swing)

### Identity
- **Registered name:** `"Relative Strength Momentum"`
- **Class:** `RelativeStrengthStrategy` → `strategies/relative_strength_strategy.py`
- **Engine:** `RelativeStrengthEngine` → `engines/relative_strength_engine.py`

### Thesis
Capture momentum breakouts on the 15m timeframe using relative strength vs
NIFTY, volume surges, VWAP separation, and price acceleration. Designed as a
**swing** strategy (hold overnight, exit at next close) to reduce intraday
cost drag. LONG-only — SHORT was net-negative after costs (−₹323k).

### Scoring — 7 Factors (raw capacity 100)
| Factor | Max | What it measures |
|--------|:---:|------------------|
| rs_vs_nifty | 25 | Stock vs NIFTY 1-bar and 3-bar returns |
| volume_surge | 20 | Last-bar volume / 20-bar avg; vol_ratio > 3 → max |
| vwap_separation | 15 | Price vs VWAP % + VWAP slope direction |
| breakout_range | 15 | Position in 5-bar range (near high > 90% → max) |
| price_acceleration | 10 | ROC_3 > ROC_5 and both positive |
| nifty_context | 10 | NIFTY range tightness + low change |
| intraday_structure | 5 | HH count + bullish candle ratio |

**Score threshold:** `min_score=55` (LONG requires bullish_total ≥ 55).

### Entry Rules
- **Time gates:** 10:00–11:45, 14:00–14:15, 14:45–15:00 IST (targeted windows,
  Phase 18 — replaced the flat 14:30–15:15 gate which averaged +0.0097R)
- **Day-of-week multipliers:** Thu ×0.0 (skip), Wed ×0.5, Fri ×1.05
  (Phase 23 — Thursday avgR −0.117 in every session)
- **Per-symbol tuning:** SL/TP overrides from `data/rsm_swing_tunings.json`
  (42 symbols tuned; 8 survive OOS prune)

### Exit Rules
- **Default SL/TP:** sl=2.0, tp=4.0 (swing defaults)
- **Dominant tuning:** sl=1.5 / tp=6.0 (24/42 tuned symbols)
- **Max hold:** 200 bars (backtest cap)
- **Exit mode:** next_close (overnight swing hold)

### Direction
LONG-only. SHORT hard-blocked at the strategy level (line 99: `if direction
!= "LONG": return StrategyResult()`).

### Timeframe
15m bars, swing mode (`--no-intraday`).

### Watchlist
- **Key:** `rsm_swing` (8 symbols)
- **Full backup:** `rsm_swing_full_42`
- **Symbols:** HFCL, DMART, TITAGARH, KIRLOSENG, PAYTM, OFSS, NEWGEN, BSE
- **Validation:** 50/50 time-split OOS (Phase 27). All 8 net-positive in both halves.

### Backtest Results (Phase 27 — 730d, 15m swing, net of costs)
| Metric | Value |
|--------|-------|
| Trades | 1,161 (pruned 8-sym) / 5,410 (full 76-sym backtest) |
| Net PnL | **+₹104,027** (pre-prune: −₹105,940) |
| WR | ~38.5% |
| Profitable symbols | 8/8 |
| OOS method | 50/50 time split; train-select → test-measure |

### Key Files
| File | Description |
|------|-------------|
| `engines/relative_strength_engine.py` | 7-factor momentum engine |
| `strategies/relative_strength_strategy.py` | Strategy wrapper (LONG-only) |
| `data/rsm_swing_tunings.json` | 42 per-symbol SL/TP tunings |
| `data/symbol_watchlists.json` | `rsm_swing` (8) + `rsm_swing_full_42` |
| `data/backtest_trades_15m_rsm_swing.json` | Full 5,410 trades |
| `data/backtest_trades_15m_rsm_pruned.json` | Pruned 1,161 trades |
| `scripts/tune_rsm_sltp.py` | Per-symbol SL/TP grid tuner |

### Phase Log References
- **Phase B** — RSM Swing full design, 5,410 trades, per-symbol tuning
- **Phase 18** — Targeted entry windows (10:00–11:45, 14:00–14:15, 14:45–15:00)
- **Phase 23** — Day-of-week gates (Thu skip, Wed 0.5×, Fri 1.05×)
- **Phase 27** — OOS prune 42→8, net-positive turnaround

---

## 2. Combined Swing

### Identity
- **Registered name:** `"Combined Swing"`
- **Class:** `CombinedSwingStrategy` → `strategies/combined_swing_strategy.py`
- **Engine:** `RelativeStrengthEngine` (same 7-factor engine as RSM)

### Thesis
Day-aware RSM swing with per-day entry windows tuned from backtest timestamps.
Uses the same engine as RSM but adds hard-coded day-of-week × time gates.
LONG-only.

### Scoring
Same 7-factor `RelativeStrengthEngine` as RSM (see Strategy #1).

### Entry Rules
- **Day-aware entry windows** (hard-coded in `DAY_WINDOWS`):
  - Mon: 09:30–11:00
  - Tue: **No entry** (worst day for RSM swing)
  - Wed: 10:00–11:45 + 14:30–15:25
  - Thu: 09:15 + 10:00–10:45 + 14:00–15:00
  - Fri: 09:30–10:45 + 11:15–11:30 + 14:30–15:25
- **LONG-only:** SHORT blocked at strategy level
- **Per-symbol tuning:** From `data/combined_swing_tunings.json`

### Exit Rules
- **Default SL/TP:** sl=2.0, tp=4.0
- **Dominant tuning:** sl=1.5 / tp=3.0 (e.g., LAURUSLABS PF 18.15, HCLTECH PF 5.96)
- **Max hold:** 200 bars
- **Exit mode:** next_close (overnight swing hold)

### Direction
LONG-only.

### Timeframe
15m bars, swing mode.

### Watchlist
- **Key:** `combined_swing` (17 symbols)
- **Full backup:** `combined_swing_full_64`
- **Symbols:** NETWEB, SIGNATURE, FORTIS, NYKAA, TRENT, BHEL, SUMICHEM, PAYTM,
  ABB, OFSS, BSE, ADANIENT, SBIN, MAXHEALTH, HINDUNILVR, LAURUSLABS, BPCL
- **Validation:** 60/40 train/test time split (Phase 25). 17/17 net-positive
  in both halves. 65% persistence rate (moderate — see caveat).

### Backtest Results (Phase 25/27 — 730d, 15m swing, net of costs)
| Metric | Value |
|--------|-------|
| Trades | 1,211 (pruned 17-sym) / 4,504 (full 64-sym) |
| Net PnL | **+₹162,382** (pre-prune 64-sym: −₹10,095) |
| WR | 45.6% |
| Gross avgR | +0.436 |
| Profitable symbols | 17/17 |

### Caveat
Symbol selection is moderately unstable — 65% persistence rate in 60/40 split.
Same fragility pattern as 1h swing (Phase 6). The 17-symbol set is the best
available; re-validate periodically.

### Key Files
| File | Description |
|------|-------------|
| `strategies/combined_swing_strategy.py` | Day-aware entry windows |
| `engines/relative_strength_engine.py` | Shared 7-factor engine |
| `data/combined_swing_tunings.json` | 17 per-symbol tunings |
| `data/symbol_watchlists.json` | `combined_swing` (17) + `combined_swing_full_64` |
| `data/backtest_trades_15m_combined_final.json` | 1,211 pruned trades |
| `data/backtest_trades_15mcombined_valid.json` | 4,504 full trades |
| `scripts/tune_combined_sltp.py` | Per-symbol SL/TP grid tuner |
| `scripts/build_combined_watchlist.py` | Watchlist builder |

### Phase Log References
- **Phase 19** — First build (64 syms), per-symbol tunings, scanner tier
- **Phase 25** — OOS validation, cache bug fix, prune 64→17
- **Phase 27** — Consolidated backtest confirming net-positive for 17

---

## 3. Manual Institutional (Time-Gated)

### Identity
- **Registered name:** `"Manual Institutional (time-gated)"`
- **Class:** `ManualInstitutionalStrategy` → `strategies/manual_institutional_strategy.py`
- **Engine:** `InstitutionalProbabilityEngine` → `engines/institutional_probability_engine.py`

### Thesis
Encodes the user's discretionary manual strategy — the most complex engine
(11 factors, 1276 lines). Designed to replicate institutional-grade trade
selection with strict time gates, RR filters, and bar confirmation.
LONG-only in deployed form.

### Scoring — 11 Factors (raw capacity 123 per side, clamped 0–100)
| Factor | Max | What it measures |
|--------|:---:|------------------|
| Market Regime | 15 | NIFTY EMA alignment, swing structure, day type, VIX, Bank Nifty RS |
| Sector Strength | 12 | Stock type (RS_LEADER→BREAKDOWN) + RVOL tier |
| Price Action | 16 | Swing structure, breakout/resistance, support proximity, VWAP/EMA |
| Volume | 12 | RVOL directional (high vol + price up = bullish) |
| Breakout Quality | 10 | Resistance break, volume confirm, retest, market alignment |
| Risk/Reward | 8 | RR from swing points vs ATR-based SL/TP (institutional ≥2.5) |
| Indicators | 5 | EMA alignment, RSI, MACD, VWAP |
| Catalyst | 5 | Accumulation/distribution, dips absorbed, failed bounces |
| Session Timing | 10 | Time-of-day weights (currently neutral) |
| Historical Perf. | 10 | Trailing returns (5/20/60/120d) + RS vs NIFTY |
| Short Context | 0/20 | Dedicated bearish evidence (disabled for deployed LONG-only) |

**Thresholds:** LONG requires bullish_total ≥ 70. SHORT_MIN_SCORE = 40
(effectively disabled; strategy never emits SHORT).

### Entry Rules (4 Hard Gates)
1. **TIME GATE:** Golden windows only — 09:45–10:30 and 13:30–14:30 IST
   (boundary-inclusive, configurable).
2. **RR FILTER:** Reject setups where reward:risk < `MANUAL_MIN_RR=1.5`.
3. **WEDNESDAY SKIP:** `SKIP_WEDNESDAY=1` — Wednesday avgR = +0.002, break-even.
4. **BAR CONFIRMATION:** Signal bar must have `close > open` (bullish) AND
   `volume > 1.3 × prior-bar volume` (Phase 24 — flips Manual from net loss
   to net profit by cutting ~80% of trades).
5. **Day-of-week multipliers:** Mon ×1.30, Wed ×0.0, Fri ×1.10 (Phase 23).

### Exit Rules
- **Default SL/TP:** sl=0.5, tp=5.0
- **Per-symbol tuning:** 57 symbols tuned; 9 survive OOS prune. Dominant
  pattern: sl=0.3 / tp=6.0–8.0 (51/57 use sl=0.3). Note: tight stops mean
  large notional → costs dominate (cost-in-R ~0.74R for sl=0.3).
- **Separate morning/evening tunings:** `manual_morning_tunings.json` and
  `manual_evening_tunings.json` (window-tunings take highest precedence).

### Direction
LONG-only. SHORT hard-blocked at the strategy level.

### Timeframe
15m bars, intraday (squared off EOD).

### Watchlist
- **Morning key:** `manual_morning_deploy` (9 symbols)
- **Evening key:** `manual_evening_deploy` (5 symbols)
- **Morning symbols:** CEMPRO, GODREJIND, IDEA, NEWGEN, NLCINDIA, ONGC,
  SUMICHEM, THERMAX, TITAGARH
- **Evening symbols:** CEMPRO, GODREJIND, NEWGEN, NLCINDIA, SUMICHEM
- **Full backup:** `manual_morning_deploy_full` (68), `manual_evening_deploy_full` (40)
- **Validation:** 50/50 time-split OOS (Phase 27).

### Backtest Results (Phase 27 — 730d, 15m intraday, net of costs)
| Metric | Value |
|--------|-------|
| Trades | 446 (pruned 9+5 syms) / 3,798 (full 73 syms) |
| Net PnL | **+₹68,469** (pre-prune: −₹35,694) |
| WR | 12.9% |
| Gross avgR | +0.725 (costs eat most — tight stops force large notional) |
| Profitable symbols | 9/9 |

### Key Files
| File | Description |
|------|-------------|
| `engines/institutional_probability_engine.py` | 11-factor engine (1276 lines) |
| `strategies/manual_institutional_strategy.py` | Time gates, Wednesday skip, RR filter |
| `data/manual_symbol_tunings.json` | 57 per-symbol tunings |
| `data/symbol_watchlists.json` | `manual_morning_deploy` (9), `manual_evening_deploy` (5) |
| `data/backtest_trades_15m_manual_final.json` | Pre-prune (73 syms, 3,798 trades) |
| `data/backtest_trades_15m_manual_pruned.json` | Post-prune (9 syms, 446 trades) |
| `scripts/backtest.py` | `_confirmation_gate()` (lines 883–915) |
| `scripts/tune_manual_sltp.py` | Per-symbol SL/TP grid tuner |
| `scripts/capital_model.py` | Day-of-week multipliers |

### Phase Log References
- **Phase A** — Wednesday skip, conviction recalibration, Monday boost,
  per-symbol tuning, golden window boundary fix
- **Phase 24** — Bar confirmation gate (Manual-only): −₹184k → +₹44k
- **Phase 27** — OOS prune 73→9, net-positive turnaround

---

## 4. ML Standalone

### Identity
- **Registered name:** `"ML Standalone"`
- **Class:** `MLStrategy` → `strategies/ml_strategy.py`
- **Engine:** None (XGBoost classifier, no separate engine)

### Thesis
Use machine learning to GENERATE entries from raw market state, rather than
filtering an existing strategy's signals. At each bar, the model scores BOTH
a LONG and a SHORT entry and takes whichever clears the 0.80 threshold.
Extreme selectivity (~0.2-0.3% of bars) — a low-turnover, high-quality sleeve.

### Model
- **Model file:** `data/ml_strategy_model.json`
- **Meta file:** `data/ml_strategy_model_meta.json`
- **Algorithm:** XGBoost classifier (`n_estimators=300`, `max_depth=6`)
- **Threshold:** 0.80 (fixed a-priori, walk-forward validated across 4 folds)
- **Features:** 35 total (RSI, ATR%, volume ratio, BB width, EMA distances,
  30m/1d returns + trends, NIFTY context, hour, weekday, direction one-hot)
- **SL/TP:** sl=0.5%, tp=5.0% (baked into training labels)
- **Max hold:** 96 bars
- **Directions:** LONG and SHORT (symmetric — takes best-scoring direction)

### Dataset
- **File:** `data/ml_strategy_dataset.parquet`
- **Size:** 3,980,645 labeled entries
- **Generation:** Every 3rd bar of 152 symbols × 15m × 2yr; each bar
  forward-simulates a trade (SL 0.5%/TP 5%/96 bars), label = `pnl_net > 0`
- **Base rate:** ~13% net-positive labels

### Entry Rules
- At each 15m bar, score both LONG and SHORT; take best if proba ≥ 0.80.
- **NIFTY regime gate:** Block LONG when NIFTY daily trend is DOWN
  (protects bear-market bleed).
- **Gate bypasses in paper trader:** SHORT forced on, multi_tf_filter disabled,
  day-of-week skipped (weekday is a model feature), ML filter skipped
  (model has no strategy tag column for ML Standalone).

### Exit Rules
- Fixed SL 0.5% / TP 5.0% (baked into labels; `--sl/--tp` CLI ignored).
- Max hold: 96 bars.

### Direction
LONG and SHORT (symmetric, regime-robust).

### Timeframe
15m bars.

### Watchlist
- **Key:** `full_universe` (153 symbols) — scans the full universe and lets
  the model select entries dynamically.

### Backtest Results (Phase 31 — 730d, 15m, `--no-multi-tf`)
| Metric | Value |
|--------|-------|
| Walk-forward OOS (4 folds, fixed thr 0.80) | 71 trades, **+₹49,985**, WR 38%, positive ALL 4 folds |
| 5-symbol live-path test | 43 trades, **+₹31,812**, WR 46.5%, 4/5 profitable |
| Full model (retrained on 3.98M rows) | test_net=₹127,357, test_trades=190 |

### Key Files
| File | Description |
|------|-------------|
| `strategies/ml_strategy.py` | Strategy wrapper |
| `data/ml_strategy_model.json` | Trained XGBoost model |
| `data/ml_strategy_model_meta.json` | Meta: 35 features, threshold 0.80 |
| `data/ml_strategy_dataset.parquet` | 3.98M labeled entries |
| `scripts/ml_strategy_dataset.py` | Bar-level dataset generator |
| `scripts/train_ml_strategy.py` | Trainer (3-way time split) |
| `scripts/walkforward_ml_strategy.py` | 4-fold walk-forward validator |
| `data/backtest_trades_15m_ml_standalone_test.json` | 5-sym live-path test (43 trades) |

### Phase Log References
- **Phase 31** — Full design, 1.26M→3.98M dataset, walk-forward OOS, 5-sym test
- **Phase 34** — Wired as 4th paper trader sleeve, gate bypasses

---

## 5. Daily Trend Breakout

### Identity
- **Registered name:** `"Daily Trend Breakout"`
- **Class:** `DailyTrendBreakoutStrategy` → `strategies/daily_trend_strategy.py`
- **Engine:** `DailyTrendEngine` → `engines/daily_trend_engine.py`

### Thesis
Capture large 10–50%+ trending moves that fixed-SL/TP strategies (RSM,
Combined, Manual, ML Standalone) structurally cannot — none let winners run.
Uses a Donchian channel breakout trigger + 6-factor quality score + close-based
chandelier trailing stop with NO fixed take-profit. The fat-tailed nature
(top 5% of trades drive 90% of PnL) is by design.

### Scoring — Donchian Breakout + 6 Factors
**Core trigger:** Close > prior N-bar high (Donchian channel=15). No breakout
= no trade (returns immediately).

| Factor | Max | What it measures |
|--------|:---:|------------------|
| Breakout Strength | 20 | Distance above channel high, in ATR units (clip at 1.0 ATR) |
| Trend Quality | 25 | SMA50 > SMA200 (+12), price above SMA50 (+7), above SMA200 (+6) |
| Volume Confirmation | 15 | Breakout-bar volume vs 20-bar avg (clip at 2.0×) |
| Trend Strength (ADX proxy) | 15 | Directional movement / ATR (scaled to 40 ADX = 15pts) |
| RSI Momentum | 15 | RSI 55–75 = 15pts, >82 = 3 (overbought penalty), <50 = 2 |
| RS vs NIFTY | 10 | Stock 20-bar ret minus NIFTY 20-bar ret (neutral default 5) |
| **Total** | **100** | Sum (no breakout → 0) |

**Min score:** 60 (default).

### Entry Rules
- Donchian channel(15) breakout on daily close.
- Entry at **next-day 09:15 open** (paper trader's `_decide_daily()`).
- LONG-only (SHORT intentionally not implemented).

### Exit Rules — Trailing ATR Stop (No Fixed TP)
- **Trailing stop:** Close-based chandelier — `hwm = highest close since entry`;
  `stop = max(initial_stop, hwm − trail_atr_mult × ATR)`. Exit when close ≤ stop.
- **Initial SL:** `initial_sl_atr = 4.0` (entry − 4 × ATR).
- **Trail multiplier:** `trail_atr_mult = 4.0`.
- **Max hold:** 60 daily bars (~3 months).
- **No fixed TP:** `take_profit` set to sentinel (entry × 5, ignored because
  `trail_atr_mult > 0`).

### Known Weakness
The chandelier only ratchets UP. When a stock gaps down sharply day after day,
the stop doesn't tighten — exit can happen far below initial SL. 10.2% of
backtest trades have r_multiple < −1.0; worst (VEDL) lost 5.3R (−₹2,584).
This is the cost of letting winners run.

### Direction
LONG-only.

### Timeframe
1d (daily bars).

### Watchlist
- **Key:** `daily_trend_breakout` (108 symbols)
- **Conservative variant:** `daily_trend_breakout_robust` (33 symbols,
  both-halves positive — arguably too strict for a fat-tailed strategy)
- **Validation:** 452 symbols × 5yr backtest, 171 traded. 108 net-positive
  with ≥10 trades. No OOS time-split (strategy is too recent).

### Backtest Results (Phase 36 — 1825d daily, 500-sym NSE universe, `--no-multi-tf`)
| Metric | Value |
|--------|-------|
| Trades | 6,903 (171 symbols traded of 500) |
| Net PnL | **+₹1,992,944** (after costs) |
| WR | 48.3% |
| Avg net/trade | +₹289 |
| AvgR | +0.501 |
| Top symbols | MAZDOCK +₹106k, BSE +₹101k, RVNL +₹76k, RECLTD +₹72k |
| Profitable | 114 symbols net-positive; 108 with ≥10 trades |

**Concept test** (452 syms, 5yr, gross): 4,702 tr, avg +3.29%, PF 1.93,
WR 40.9%, avg win +16.75%, max win +172%.

### Key Files
| File | Description |
|------|-------------|
| `engines/daily_trend_engine.py` | 6-factor Donchian breakout scorer |
| `strategies/daily_trend_strategy.py` | Trailing ATR stop, LONG-only |
| `strategies/executable.py` | `TradeCandidate.trail_atr_mult` / `max_hold_bars` |
| `scripts/backtest.py` | Trailing exit, signed-R settle, EXPIRED equity fix |
| `scripts/paper_trade.py` | `_build_daily_context`, `_decide_daily`, `_daily_trailing_exit` |
| `data/symbol_watchlists.json` | `daily_trend_breakout` (108), `_robust` (33) |
| `data/backtest_trades_1d_daily_trend_full.json` | 6,903 trades |
| `data/backtest_portfolio_1d_daily_trend_full.json` | Portfolio summary |

### Phase Log References
- **Phase 36** — Full build: engine, strategy, 500-sym backtest, net +₹2M
- **Phase 37** — Deployed as 5th paper sleeve, 108-sym watchlist

---

## 6. ML Opening Breakout (ORB ML)

### Identity
- **Registered name:** `"ML Opening Breakout"`
- **Class:** `MLOpeningBreakoutStrategy` → `strategies/orb_ml_strategy.py`
- **Engine:** None (XGBoost classifier, no separate engine)

### Thesis
Predict net-profitable opening-range-breakout trades using ML on the first
~75 minutes of each trading day. At each 5-minute bar in the 09:15–10:30 IST
opening window, scores BOTH LONG and SHORT and takes whichever clears the
deploy threshold (default 0.70). The model uses gap, opening range, and
first-bar features that encode the opening auction's information.

### Model
- **Model file:** `data/ml_orb_model.json`
- **Meta file:** `data/ml_orb_model_meta.json`
- **Algorithm:** XGBoost classifier
- **Threshold:** 0.70 (deploy default; model meta threshold is 0.50)
- **AUC (test):** 0.681
- **Features:** 33 total — gap_pct, opening_range_15m/30m_pct, price_position
  in range, first_bar_return/range/volume_ratio, cum_return_since_open,
  minutes_since_open, prev_day_range/return, RSI, ATR%, volume_ratio, BB width,
  EMA distances, NIFTY 1d return, NIFTY gap, hour, minute, weekday,
  direction one-hot, gap_dir categories, nifty_1d_trend categories
- **SL/TP:** sl=0.3%, tp=1.5% (baked into training labels)
- **Max hold:** 48 bars (~4 hours)
- **Directions:** LONG and SHORT (both scored, best taken)

### Dataset & Training
- **Dataset:** `data/ml_orb_dataset.parquet` (50MB) + test set
  `data/ml_orb_dataset_test.parquet` (2.2MB)
- **Train/Test split:** 431,781 train / 185,050 test rows
- **Training script:** `scripts/train_ml_orb.py`
- **Test net PnL (from meta):** ₹1,331,130 (model test set, not capital-constrained)

### Entry Rules
- **Time gate:** Only the most recent completed 5m bar inside 09:15–10:30 IST
  opening window is evaluated. At each such bar:
  1. Compute stock features + opening features + NIFTY context.
  2. Score both LONG and SHORT via the XGBoost model.
  3. Take best direction if proba ≥ 0.70.
- **Gate bypasses:** multi_tf_filter disabled, HTF alignment filter bypassed
  (model features encode timing/regime).

### Exit Rules
- Fixed SL 0.3% / TP 1.5% (baked into training labels).
- Max hold: 48 bars (~4 hours, end of session).

### Direction
LONG and SHORT (both scored, best taken).

### Timeframe
5m bars (opening window only: 09:15–10:30 IST).

### Watchlist
- **Scanner tier:** `("orb_scan", "full_nse_500", "intraday", {tf:"5m", ...})`
- **Paper trader:** `STRATEGY_WATCHLISTS["ML Opening Breakout"] = ["full_nse_500"]`
- **Size:** 500 symbols (full NSE universe).

### Backtest Results (500-sym full run, derived from `data/orb_ml_results_0.7.json`)
| Metric | Value (thr=0.70) | Notes |
|--------|:----------------:|-------|
| Trades | 41,321 | Every opening-window bar scored across 500 syms × ~2yr |
| WR | 84.0% | % of trades hitting TP vs SL |
| Avg net ret/trade | +0.981% | Percentage return on notional (not ₹ PnL) |
| Total net ret (sum) | +40,534% | Sum of per-trade % returns |
| LONG trades | 18,158 / WR 84.2% / avg +0.995% | |
| SHORT trades | 23,163 / WR 83.9% / avg +0.970% | |
| Model test net PnL | ₹1,331,130 | From meta (test set, not capital-constrained) |

> **Note:** The ORB results are percentage-return based (net_ret per trade).
> A proper capital-constrained backtest with position sizing has not been run
> for the 500-sym universe. The model test_net_pnl of ₹1,331,130 is from the
> ML train/test split and does not reflect the ₹50k capital limit, daily cap,
> or concurrency constraints. The percentage returns (84% WR, +0.981%/trade)
> suggest a real edge, but the rupee PnL in the live paper trader will be
> lower due to position sizing bounds.

### Key Files
| File | Description |
|------|-------------|
| `strategies/orb_ml_strategy.py` | ML Opening Breakout strategy (window gate, model inference) |
| `data/ml_orb_model.json` | Trained XGBoost model (1.5MB) |
| `data/ml_orb_model_meta.json` | Meta: 33 features, thr 0.70, SL 0.3%/TP 1.5% |
| `data/ml_orb_dataset.parquet` | Full labeled dataset (50MB) |
| `scripts/ml_dataset_orb_5m.py` | Dataset generator (stock features + opening features + NIFTY context) |
| `scripts/backtest_orb_ml.py` | 5m ORB ML backtest harness |
| `scripts/train_ml_orb.py` | ML ORB trainer |
| `data/orb_ml_results_0.7.json` | 41,321 backtest trades @ thr 0.70 |

### Phase Log References
- **Phase D** (not in AGENTS.md as a dedicated phase section) — The strategy
  was deployed directly as the 6th sleeve in `start_all.sh`. Backtest and
  model training occurred on 2026-07-20.

---

## Comparison Table

| # | Strategy | Engine/Model | Dir | TF | Watchlist | Syms | Net PnL (₹) | Trades | WR | Validated By |
|---|----------|-------------|:---:|:--:|-----------|:----:|:-----------:|:------:|:--:|-------------|
| 1 | RSM Swing | 7-factor RSM Engine | LONG | 15m | `rsm_swing` | 8 | +104,027 | 1,161 | 38.5% | 50/50 time split |
| 2 | Combined Swing | 7-factor RSM Engine | LONG | 15m | `combined_swing` | 17 | +162,382 | 1,211 | 45.6% | 60/40 time split |
| 3 | Manual Inst. | 11-factor IP Engine | LONG | 15m | `manual_*_deploy` | 9+5 | +68,469 | 446 | 12.9% | 50/50 time split |
| 4 | ML Standalone | XGBoost (35 feat, thr 0.80) | BOTH | 15m | `full_universe` | 153 | +49,985 | 71 | 38% | 4-fold walk-forward |
| 5 | Daily Trend | 6-factor + Donchian | LONG | 1d | `daily_trend_breakout` | 108 | +1,992,944 | 6,903 | 48.3% | 5yr cross-section |
| 6 | ML Opening Brk | XGBoost (33 feat, thr 0.70) | BOTH | 5m | `full_nse_500` | 500 | +40,534%* | 41,321 | 84.0% | Train/test split |

> \* ML Opening Breakout net PnL is percentage-return sum (not capital-constrained ₹).
> Model test set reports ₹1,331,130 test_net_pnl (unconstrained).

## Combined Portfolio (all 6, paper trader)

| Metric | Value |
|--------|-------|
| Total capital | ₹50,000 |
| Risk per trade | 1% (₹500) |
| Max entries/day | 30 (5 × 6 strategies) |
| Allocations | RSM 18%, Combined 22%, Manual 18%, ML Standalone 14%, Daily Trend 18%, ORB 10% |
| Mode | `--mode both` |
| Scanner | `--upstox --serve --port 8080` |
| ML Filter | `--ml-filter --ml-filter-thr 0.60` (applied to RSM/Combined/Manual only) |

## Data File Index

### Engine Files
| Strategy | Engine Path |
|----------|-------------|
| RSM / Combined | `engines/relative_strength_engine.py` |
| Manual | `engines/institutional_probability_engine.py` |
| Daily Trend | `engines/daily_trend_engine.py` |
| ML Standalone | (none — XGBoost) |
| ML Opening Breakout | (none — XGBoost) |

### Strategy Files
| Strategy | Strategy Path |
|----------|--------------|
| RSM | `strategies/relative_strength_strategy.py` |
| Combined | `strategies/combined_swing_strategy.py` |
| Manual | `strategies/manual_institutional_strategy.py` |
| ML Standalone | `strategies/ml_strategy.py` |
| Daily Trend | `strategies/daily_trend_strategy.py` |
| ML Opening Breakout | `strategies/orb_ml_strategy.py` |

### Tuning Files
| Strategy | Tuning Path |
|----------|-------------|
| RSM | `data/rsm_swing_tunings.json` |
| Combined | `data/combined_swing_tunings.json` |
| Manual | `data/manual_symbol_tunings.json` |
| Daily Trend | (not yet built) |
| ML Standalone | (model params in meta) |
| ML Opening Breakout | (model params in meta) |

### Backtest Trade Files
| Strategy | Trade file | Trades |
|----------|------------|:------:|
| RSM (full) | `data/backtest_trades_15m_rsm_swing.json` | 5,410 |
| RSM (pruned) | `data/backtest_trades_15m_rsm_pruned.json` | 1,161 |
| Combined (pruned) | `data/backtest_trades_15m_combined_final.json` | 1,211 |
| Combined (full) | `data/backtest_trades_15mcombined_valid.json` | 4,504 |
| Manual (full) | `data/backtest_trades_15m_manual_final.json` | 3,798 |
| Manual (pruned) | `data/backtest_trades_15m_manual_pruned.json` | 446 |
| ML Standalone (test) | `data/backtest_trades_15m_ml_standalone_test.json` | 43 |
| Daily Trend | `data/backtest_trades_1d_daily_trend_full.json` | 6,903 |
| ML Opening Breakout | `data/orb_ml_results_0.7.json` | 41,321 |

### Model Files
| Strategy | Model | Meta |
|----------|-------|------|
| ML Standalone | `data/ml_strategy_model.json` | `data/ml_strategy_model_meta.json` |
| ML Opening Breakout | `data/ml_orb_model.json` | `data/ml_orb_model_meta.json` |

### ML Filter
| File | Description |
|------|-------------|
| `data/ml_filter_all.json` | Universal filter model (Phase 32, 43 features, thr 0.65) |
| `data/ml_filter_all_meta.json` | Meta (thr 0.65, features, deployment params) |
| `scripts/ml_filter_gate.py` | Live filter inference wrapper |
| `scripts/train_ml_filter_all.py` | Options A + C trainer |
| `data/backtest_trades_15m_mlall_{rsm,combined,manual}.json` | 28,215 pooled training trades |

### Scanner / Paper Trader
| File | Description |
|------|-------------|
| `scripts/market_scan.py` | Live dashboard scanner (6 tiers) |
| `scripts/paper_trade.py` | Paper/real trader (all 6 strategies) |
| `scripts/start_all.sh` | Launch script (paper + scanner + data refresher) |
| `web/dashboard.html` | Live web dashboard |

### Watchlist
| File | Description |
|------|-------------|
| `data/symbol_watchlists.json` | All watchlists (6 strategies) |

---

*Generated 2026-07-21. Backtest results are net of costs (STT 0.025%, brokerage,
slippage) unless marked otherwise. All rupee values are on the ₹50k capital model
with 1% risk-per-trade.*
