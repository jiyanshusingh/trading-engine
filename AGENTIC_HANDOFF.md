# AGENTIC HANDOFF — Institutional Trading AI

> Read this FIRST when picking up this project. It is the cold-start map for an
> agentic AI. Every number here was verified against the actual files on disk
> as of 2026-07-14. Re-verify any specific claim against the cited file before
> acting on it — the owner distrusts stale docs and assumptions.

---

## PROJECT PURPOSE
Python algo-trading system for NSE Indian equities. Goal: **positive net PnL
after costs** via a small set of validated intraday strategies. Capital model is
**₹50,000 paper capital, 1% risk/trade (₹500), max 5 new entries/day**. No real
orders placed unless `--real` + trading-scoped Upstox token (currently the
`.env` token is data-scoped only → live orders would be rejected).

## THE #1 RULE (from the owner)
Do NOT assert strategy counts, live status, or any result from memory or
AGENTS.md alone. ALWAYS ground claims in ACTUAL files:
- `data/paper_portfolio.json` — live/paper portfolio state
- `data/backtest_portfolio_15m*.json` — per-symbol backtest summaries
- `data/backtest_trades_15m*.json` — per-trade records
- `data/manual_strategy_watchlist.json` — the manual strategy's watchlist
- `data/symbol_watchlists.json` — the paper trader's watchlist source
- source in `engines/`, `strategies/`, `scripts/`

## THREE LIVE STRATEGIES (registered in `strategies/selector.py`)
1. **"Institutional Probability"** — 11-factor engine
   (`strategies/institutional_strategy.py` → `engines/institutional_probability_engine.py`)
2. **"Relative Strength Momentum"** — RSI-based
   (`strategies/relative_strength_strategy.py`)
3. **"Manual Institutional (time-gated)"** — NEW (added 2026-07-13/14)
   (`strategies/manual_institutional_strategy.py`)

## THE NEW STRATEGY — "Manual Institutional (time-gated)"
Encodes the owner's discretionary method that worked in two golden intraday
windows: **09:45–10:30 and 13:30–14:30 IST**. LONG-only breakout/momentum.

Implementation (READ `strategies/manual_institutional_strategy.py`):
- Reuses `InstitutionalProbabilityEngine` (the 100-point model: market regime
  15%, sector 15%, price action 20%, volume 15%, breakout 15%, RR 10%,
  indicators 5%, catalyst 5%). Does NOT re-implement scoring.
- Layers 3 HARD GATES on top of engine output:
  - GATE 1 (TIME): `entry_time` must fall inside `GOLDEN_WINDOWS`, else NONE.
  - GATE 2 (LONG+SCORE): `bullish_score >= MANUAL_MIN_SCORE`, else NONE.
  - GATE 3 (RR): `reward:risk >= MANUAL_MIN_RR`, else NONE.
- SL/TP: ATR-based, `sl_mult=0.5, tp_mult=5.0, atr_period=14` (~10:1 RR).
- Env-tunable: `MANUAL_MIN_SCORE` (default **40**), `MANUAL_MIN_RR` (default **1.5**).
  `GOLDEN_WINDOWS` is hardcoded tuples (code change to move).

## CRITICAL TECHNICAL FINDINGS — the traps that cost hours
1. **ENGINE SCORE SCALE MISMATCH**: the engine's clamped `bullish_score` maxes
   at ~56–77, mean ~50 on real 15m data. The owner's mental "80/100 probability"
   scale does NOT map. Correct LONG threshold for this strategy is **40, NOT 70**.
   Setting 70 → ZERO trades.
2. **DOUBLE THRESHOLD GATE**: two independent gates must both pass:
   (a) strategy's `MANUAL_MIN_SCORE` (`strategies/manual_institutional_strategy.py`);
   (b) `backtest.py`'s `MIN_PROB = LONG_MIN_SCORE` (env `INST_LONG_MIN_SCORE`,
   default 70). To run this strategy set **BOTH** `MANUAL_MIN_SCORE=40` AND
   `INST_LONG_MIN_SCORE=40`, or the backtest silently rejects every candidate
   (score 40 < 70).
3. **TUNING OVERRIDE REQUIRED in `run_backtest_portfolio.py`**: when `--strategy`
   is passed but `--tuning-sl/--tuning-tp` are NOT, `decide_trade()` in
   `backtest.py` falls back to DEFAULT strategy tuning `{sl_mult:3.0, tp_mult:4.0}`
   (~line 893). That wrong SL/TP breaks the RR gate → 0 trades. **FIX: always
   pass `--tuning-sl 0.5 --tuning-tp 5.0` alongside `--strategy`.** (This caused
   the first full 191-run to return 0 trades.)
4. **PROCESS TRACKER IS UNRELIABLE**: background processes launched with a
   `$(subshell)` wrapper report false "exited" notifications while still running.
   Trust the live PID (`ps -p <pid>`) and the output file's existence, NOT the
   notification. Batch runs write their JSON only at the very END.
5. **COSTS DOMINATE** (owner's central problem): with stop ~0.4–0.5% of price and
   1% risk forcing ~₹125k notional, round-trip cost ≈ ₹150/trade. The fixed
   brokerage+GST floor (~₹47/trade) alone exceeds thin gross edges. Net-positive
   needs fewer/bigger trades (wider stops) OR ~4× gross edge (selectivity). The
   manual golden-window strategy IS net-positive (see results).

## VERIFIED RESULTS — "Manual Institutional (time-gated)", 700d, 15m, real costs
- 181/191 symbols traded; 21,597 trades total.
- 76 symbols deployable (PF>=1.3, >=10 trades, net PnL>0).
- After max-drawdown <= 6% tightening: **61 symbols** ("manual_golden").
- Top: LODHA PF3.69, PWL PF3.52, AEGISLOG PF2.89, HFCL PF2.80, HCLTECH PF2.71,
  M&MFIN PF2.59, PAYTM PF2.46, RBLBANK PF2.40.
- BSE (owner's example): 386 trades, PF1.18, +14.3% net (positive, <1.3 bar).
- Edge concentrates in mid/small-caps + thematic names, NOT Nifty-50 blue chips.
- Output files on disk:
  - `data/backtest_portfolio_15m_b0final.json` (46 core names: BSE/ONGC/RELIANCE/TCS/TITAN…)
  - `data/backtest_portfolio_15m_b1.json`, `b2.json`, `b3.json` (144 names)
  - `data/backtest_portfolio_15m_coal.json` (COALINDIA)
  - `data/manual_strategy_watchlist.json` (76-name ranked + DD-tightened subset)
  - `data/symbol_watchlists.json` (key `manual_golden` = 61 names, for paper trader)

## PAPER TRADING LOOP (was running as of handoff)
- `scripts/paper_trade.py --strategy "Manual Institutional (time-gated)"
   --watchlist manual_golden --upstox --loop --interval 15`
- Env: `INST_LONG_MIN_SCORE=40 MANUAL_MIN_SCORE=40 MANUAL_MIN_RR=1.5`
- Capital ₹50,000 to the manual strategy (verified in `data/paper_portfolio.json`).
- Market-aware: skips when closed; fires only in golden windows after 09:15 open.
- Logs: `data/paper_manual_loop.log`. State: `data/paper_portfolio.json`.
- The paper trader's `--watchlist` reads ONLY `data/symbol_watchlists.json`, not
  `manual_strategy_watchlist.json`. To use a new list, add a key there.

## DATA INFRASTRUCTURE
- Cache: `data/cache/15m/*.parquet` (191 files, ~729d, Upstox 1m→15m resampled),
  `data/cache/1h/*.parquet` (111, ~3yr native), `data/cache/1d/*.parquet` (112, ~5yr).
- 15m caveat: yfinance caps 15m at 60d; 729d 15m is from Upstox (no native 15m →
  1m resampled). **LONG signals are RARE on resampled 15m** (engine needs native
  15m); SHORT works. This is why LONG stays disabled live.
- Universe: `data/downloader/watched_symbols.py` → `expansion_universe()` (118 syms).

## KEY FILES / WHERE THINGS LIVE
- Engine:        `engines/institutional_probability_engine.py`
- Strategies:    `strategies/*.py`  (registry: `strategies/selector.py`)
- Base class:    `strategies/executable.py` (ExecutableStrategy, StrategyResult, TradeCandidate)
- Backtest core: `scripts/backtest.py` (WalkForwardBacktest, decide_trade, _compute_costs)
- Portfolio run: `scripts/run_backtest_portfolio.py` (--strategy, --tuning-sl/tp,
                 --symbols, --out-suffix, --slippage {off,default,realistic}, --provider yfinance)
- Walk-forward:  `scripts/walkforward_validate.py` (--folds, --shorts, --min-pf)
- Paper trade:   `scripts/paper_trade.py` (--watchlist, --upstox, --loop, --shorts, --conviction)
- Scanner:       `scripts/market_scan.py` (--serve dashboard, --shorts, --tiers)
- Capital model: `scripts/capital_model.py` (INITIAL_CAPITAL=50000, RISK_PER_TRADE_PCT=1.0,
                 MAX_TRADES_PER_DAY=5, MAX_RISK_PCT=1.5, MAX_DRAWDOWN_PCT=15, conviction_multiplier)
- Cost model:    `scripts/backtest.py:_compute_costs` + `scripts/slippage_model.py`
                 (STT 0.025% intraday equity; brokerage ₹20/order; GST 18%; exchange fee)

## COST MODEL (exact, `scripts/backtest.py:_compute_costs`)
- fixed = brokerage ₹20×2 + GST 18% on brokerage = **₹47.20/trade**
- var   = (SLIPPAGE 0.05% + STT 0.025% + exchange 0.0002%) × notional
- Total ~₹81/trade at ₹27k notional. NOTE: STT was corrected 0.1%→0.025% this
  cycle (0.1% was delivery rate, 4× overstated).

## STATUS OF OTHER STRATEGIES (verify vs AGENTS.md before trusting)
- SHORT side: disabled live. 15m SHORT has real GROSS edge OOS-validated on 729d
  but NEGATIVE net after costs (~−0.14R with real STT). Not deployable.
- LONG (Institutional Probability): rare on resampled 15m; needs native 15m data
  (Upstox has none) → not validated OOS → disabled live.
- The manual golden-window strategy is the ONLY currently net-positive +
  cost-aware live candidate.

## KNOWN GOTCHAS FOR THE NEXT AGENT
1. Set `INST_LONG_MIN_SCORE` + `MANUAL_MIN_SCORE` together (both 40 for this strat).
2. Always pass `--tuning-sl 0.5 --tuning-tp 5.0` with `--strategy` in run_backtest_portfolio.
3. Don't trust background "exited" notifications — check PID + output file.
4. Engine scores top out ~77; never use 70+ as a live LONG threshold here.
5. `paper_trade --watchlist` only sees `data/symbol_watchlists.json`.
6. Timezone: cache 15m bars are tz-naive IST wall-clock; golden-window gate uses
   hour+minute of that timestamp.

## ENV / RUN
- Python venv at `.venv` (use `.venv/bin/python`). `requirements.txt` present.
- Backtest one strategy:
  ```
  INST_LONG_MIN_SCORE=40 MANUAL_MIN_SCORE=40 MANUAL_MIN_RR=1.5 \
  .venv/bin/python scripts/run_backtest_portfolio.py \
    --timeframe 15m --strategy "Manual Institutional (time-gated)" \
    --provider yfinance --days 700 --slippage default \
    --tuning-sl 0.5 --tuning-tp 5.0 --symbols BSE,ONGC --out-suffix _test
  ```
- Paper loop:
  ```
  INST_LONG_MIN_SCORE=40 MANUAL_MIN_SCORE=40 MANUAL_MIN_RR=1.5 \
  .venv/bin/python scripts/paper_trade.py \
    --strategy "Manual Institutional (time-gated)" \
    --watchlist manual_golden --upstox --loop --interval 15
  ```

---
Generated 2026-07-14. Re-verify specifics against cited files before acting.
