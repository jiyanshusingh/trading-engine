# Internship Report

## AI-Powered Multi-Strategy Trading System

**Intern:** [Your Name]
**Organization:** Digitaaztrans Technologies Pvt. Ltd.
**Duration:** 2 months
**Domain:** Generative AI | **Date:** July 2026

---

## Chapter 1: Introduction

### 1.1 Internship Context

I completed a two-month internship at Digitaaztrans Technologies Pvt. Ltd., where I worked in the Generative AI division. The internship focused on understanding Large Language Models, prompt engineering, AI workflow design, and building AI applications that generate decisions from data.

### 1.2 Project Motivation

As part of the internship, I was assigned a project to apply these concepts to a real-world problem. The domain chosen was automated trading — a field where AI decision-making can directly replace slow, inconsistent human analysis.

### 1.3 About the Company

Digitaaztrans Technologies Pvt. Ltd. specializes in technology solutions with a focus on Generative AI applications. The company works on building AI systems that automate complex decision-making processes across domains.

### 1.4 Report Structure

This report documents the full journey: from understanding Generative AI concepts, to designing a multi-strategy AI trading system, implementing it with 6 parallel decision engines, validating each strategy rigorously through walk-forward out-of-sample testing, and deploying it live on the Upstox platform.

---

## Chapter 2: Background — Generative AI Meets Decision Systems

### 2.1 Generative AI Concepts

During the internship, I studied:
- **Large Language Models (LLMs):** Models that generate text from input prompts
- **Prompt Engineering:** Designing input vectors that elicit the correct output from an AI model
- **Model Validation:** Ensuring models perform well on unseen data, not just training data
- **Temperature / Sampling:** Controlling how selective a model is in its outputs

### 2.2 Mapping to Trading Decisions

The key insight was that trading decision-making follows the same pipeline as Generative AI:

| Generative AI Concept | Trading AI Equivalent |
|----------------------|---------------------|
| Text prompt (input) | Feature vector (33-35 market features) |
| LLM generates tokens | XGBoost generates LONG/SHORT/NONE decision |
| Probability distribution | Class probability score (0.0-1.0) |
| Temperature (selectivity) | Decision threshold (0.70-0.80) |
| Chain-of-thought reasoning | Expert system factor evaluation (6-11 factors) |
| Training on text corpus | Training on labeled market bars (3.98M examples) |
| Validation on held-out text | Walk-forward OOS testing on unseen future periods |

### 2.3 Why Expert Systems Count as AI

Three of the six strategies use rule-based expert systems — a classic AI paradigm. Each factor (7 for RSM, 11 for Manual Institutional, 6 for Daily Trend) is evaluated sequentially, with weights, and the sum produces a decision. This is identical in structure to chain-of-thought reasoning in modern LLMs.

### 2.4 The Validation Imperative

A key learning from the internship was that AI models must be validated on data they have never seen. In trading, this is even more critical because:
- Markets are non-stationary (patterns change over time)
- Backtest overfitting is the #1 cause of failure in live trading
- Transaction costs can destroy even a statistically significant edge

---

## Chapter 3: Problem Statement

### 3.1 The Retail Trader's Challenge

Retail traders in the Indian stock market face several problems:

1. **Information Overload:** With 500+ stocks in the NSE universe, no human can monitor all of them simultaneously
2. **Emotional Decision-Making:** Fear and greed cause inconsistent trade execution
3. **No Systematic Validation:** Most traders cannot prove their strategy works — they trade on intuition
4. **High Costs:** STT (0.025%), brokerage (₹20/trade), and slippage (0.05%) eat into profits
5. **Time Constraints:** Manual analysis takes hours daily, and is prone to fatigue

### 3.2 Requirements

The system needed to:
1. Automate market data collection and analysis across 500+ stocks
2. Use multiple AI approaches (ML + expert systems) to diversify risk
3. Make decisions every 5 minutes during market hours
4. Be rigorously validated before any real-money deployment
5. Account for all transaction costs in validation
6. Run autonomously with crash recovery

### 3.3 Objectives

1. Apply Generative AI concepts to build a production-grade decision system
2. Develop 3 ML-based and 3 rule-based strategies
3. Validate every strategy through walk-forward out-of-sample testing
4. Deploy the system live with paper trading on Upstox

---

## Chapter 4: System Design

### 4.1 High-Level Architecture

```
Market Data (Upstox API)
       ↓
Feature Engineering (33-35 features per bar)
       ↓
┌──────────────────────────────────────┐
│       6 AI Decision Engines          │
├──────────────────────────────────────┤
│ ML Standalone      (XGBoost, 35 feat)│
│ ML Opening Breakout (XGBoost, 33 feat)│
│ ML Filter          (XGBoost, 43 feat)│
│ RSM Swing          (7-factor expert) │
│ Combined Swing     (7-factor expert) │
│ Manual Institutional (11-factor expert)│
│ Daily Trend Breakout (6-factor expert)│
└──────────────────────────────────────┘
       ↓
Decision Filter (confidence thresholds)
       ↓
Risk Manager (₹50k capital, 1% risk/trade)
       ↓
Order Execution (Upstox paper trading)
```

### 4.2 Strategy Design Principles

**Diversification across 3 dimensions:**
1. **Timeframe:** 5m (ORB), 15m (RSM, Combined, Manual, ML Standalone), 1d (Daily Trend)
2. **AI Approach:** ML models (3) + Expert systems (3) + Hybrid (ML Filter)
3. **Direction:** LONG-only (RSM, Combined, Manual, Daily Trend) + Both (ML Standalone, ORB)

### 4.3 The 3 ML-Based Strategies

#### 4.3.1 ML Standalone
- **Model:** XGBoost classifier (`n_estimators=300`, `max_depth=6`)
- **Training Data:** 3,980,645 labeled 15-minute bars across 152 symbols × 2 years
- **Features (35):** RSI, ATR%, volume ratio, Bollinger Band width, EMA distances (5/10/20/50), 30m and 1d returns, NIFTY context, hour, weekday, direction one-hot
- **Threshold:** 0.80 (fixed a-priori, not optimized on test data)
- **SL/TP:** 0.5% / 5.0% (baked into training labels)

#### 4.3.2 ML Opening Breakout (ORB)
- **Model:** XGBoost classifier (AUC 0.681 on test set)
- **Training Data:** 616,831 labeled 5-minute opening-window bars (09:15-10:30 IST)
- **Features (33):** gap_pct, opening_range_15m/30m_pct, price_position in range, first_bar_return/range/volume_ratio, cum_return_since_open, minutes_since_open, prev_day_range/return, RSI, ATR%, volume_ratio, BB width, EMA distances, NIFTY context
- **Threshold:** 0.70 (deploy default)
- **SL/TP:** 0.3% / 1.5% (baked into training labels)

#### 4.3.3 ML Filter
- **Model:** XGBoost classifier (trained on 28,215 pooled trades)
- **Function:** Takes a signal from RSM, Combined, or Manual strategy and predicts whether it will be net-profitable
- **Threshold:** 0.60
- **Result:** Turns a net-negative set of raw signals into a net-positive filtered subset

### 4.4 The 3 Rule-Based Strategies

#### 4.4.1 Relative Strength Momentum (RSM Swing)

**Engine:** 7-factor RelativeStrengthEngine

| Factor | Max | What It Measures |
|--------|:---:|------------------|
| rs_vs_nifty | 25 | Stock vs NIFTY 1-bar and 3-bar returns |
| volume_surge | 20 | Last-bar volume / 20-bar avg; vol_ratio > 3 → max |
| vwap_separation | 15 | Price vs VWAP % + VWAP slope direction |
| breakout_range | 15 | Position in 5-bar range |
| price_acceleration | 10 | ROC_3 > ROC_5 and both positive |
| nifty_context | 10 | NIFTY range tightness + low change |
| intraday_structure | 5 | HH count + bullish candle ratio |

**Score threshold:** 55/100

**Time gates:** 10:00-11:45, 14:00-14:15, 14:45-15:00 IST
**Day-of-week:** Thu ×0.0 (skip), Wed ×0.5, Fri ×1.05

#### 4.4.2 Combined Swing

Same 7-factor engine as RSM, but with per-day entry windows:

- Mon: 09:30-11:00
- Tue: No entry
- Wed: 10:00-11:45 + 14:30-15:25
- Thu: 09:15 + 10:00-10:45 + 14:00-15:00
- Fri: 09:30-10:45 + 11:15-11:30 + 14:30-15:25

#### 4.4.3 Manual Institutional

**Engine:** 11-factor InstitutionalProbabilityEngine (1,276 lines)

| Factor | Max | What It Measures |
|--------|:---:|------------------|
| Market Regime | 15 | NIFTY EMA alignment, swing structure, VIX, Bank Nifty RS |
| Sector Strength | 12 | Stock type (RS_LEADER→BREAKDOWN) + RVOL tier |
| Price Action | 16 | Swing structure, breakout/resistance, support proximity |
| Volume | 12 | RVOL directional |
| Breakout Quality | 10 | Resistance break, volume confirm, retest, market alignment |
| Risk/Reward | 8 | RR from swing points vs ATR-based SL/TP |
| Indicators | 5 | EMA alignment, RSI, MACD, VWAP |
| Catalyst | 5 | Accumulation/distribution, dips absorbed |
| Session Timing | 10 | Time-of-day weights |
| Historical Perf. | 10 | Trailing returns (5/20/60/120d) + RS vs NIFTY |
| Short Context | 0/20 | Bearish evidence (disabled for LONG-only mode) |

**Entry gates:**
1. TIME: 09:45-10:30 and 13:30-14:30 IST only
2. RR: Reject if reward:risk < 1.5
3. Wednesday: Skip entirely
4. Bar confirmation: close > open AND volume > 1.3× prior bar

#### 4.4.4 Daily Trend Breakout

**Engine:** 6-factor DailyTrendEngine + Donchian channel(15) breakout trigger

**Trigger:** Close above prior 15-bar high

| Factor | Max | What It Measures |
|--------|:---:|------------------|
| Breakout Strength | 20 | Distance above channel high in ATR units |
| Trend Quality | 25 | SMA50 > SMA200, price above SMAs |
| Volume Confirmation | 15 | Breakout volume vs 20-bar avg |
| ADX Proxy | 15 | Directional movement / ATR |
| RSI Momentum | 15 | RSI 55-75 optimal, overbought penalty |
| RS vs NIFTY | 10 | Stock vs index return differential |

**Exit:** Chandelier trailing stop (4× ATR), no fixed take-profit
**Max hold:** 60 daily bars (~3 months)

### 4.5 Capital Allocation

| Strategy | Allocation | Risk/Trade | Max Entries/Day |
|----------|:----------:|:----------:|:---------------:|
| RSM Swing | 18% | 1% (₹500) | 5 |
| Combined Swing | 22% | 1% (₹500) | 5 |
| Manual Institutional | 18% | 1% (₹500) | 5 |
| ML Standalone | 14% | 1% (₹500) | 5 |
| Daily Trend Breakout | 18% | 1% (₹500) | 5 |
| ML Opening Breakout | 10% | 1% (₹500) | 5 |

**Total capital:** ₹50,000 | **Total risk per trade:** ₹500 | **Max daily entries:** 30

---

## Chapter 5: Implementation

### 5.1 Technology Stack

| Technology | Purpose |
|------------|---------|
| **Python 3.10** | Main programming language |
| **XGBoost** | ML model training and inference |
| **Pandas / NumPy** | Data processing and feature engineering |
| **Upstox V2/V3 API** | Real-time and historical market data |
| **WebSocket** | Live intraday candle feed |
| **JSON** | Model storage, tuning parameters, watchlists |
| **Parquet** | Efficient storage of large datasets (3.98M rows) |
| **Streamlit** | Live web dashboard |

### 5.2 Data Pipeline

```
Upstox V3 API (729-day history)
       ↓
Historical cache (Parquet files per symbol)
       ↓
EOD refresh → Intraday merge (WebSocket during market hours)
       ↓
Feature computation (33-35 features per bar per symbol)
       ↓
Model inference / Engine evaluation
```

### 5.3 Model Training Pipeline

#### ML Standalone / ORB
1. **Dataset Generation:** For each bar, forward-simulate a trade with fixed SL/TP
2. **Labeling:** pnl_net > 0 = 1 (profitable), else 0
3. **Feature Engineering:** Compute 33-35 features from current bar + history
4. **Training:** XGBoost on 70% of data
5. **Validation:** Walk-forward across 4 folds
6. **Threshold Selection:** Fixed a-priori (not optimized on test data)

#### ML Filter
1. Collect signals from RSM/Combined/Manual strategies
2. For each signal, compute features and whether it was net-profitable
3. Train XGBoost to predict profitability probability

### 5.4 Live Execution

The system runs via `scripts/paper_trade.py` with `--loop --interval 5`:

1. Every ~5 minutes during market hours:
   - Fetch live bars via Upstox APIs
   - Merge with historical cache
   - Run all 6 strategies
   - Apply ML filter (for applicable strategies)
   - Check capital limits and daily entry caps
   - Enter positions (paper or `--real`)
   - Monitor existing positions (SL/TP/trailing)

2. After-hours:
   - EOD square-off for intraday strategies
   - Daily trailing stop check for swing/daily strategies
   - Log refresh and state persistence

---

## Chapter 6: Validation

### 6.1 Validation Methodology

Every strategy was validated on out-of-sample (OOS) data — data the model/engine had never seen during development.

**Walk-Forward Validation (ML Strategies):**

```
Fold 1: Train [Jul 2024 → Dec 2024]  → Test [Dec 2024 → May 2025]
Fold 2: Train [Jul 2024 → May 2025]  → Test [May 2025 → Sep 2025]
Fold 3: Train [Jul 2024 → Sep 2025]  → Test [Sep 2025 → Feb 2026]
Fold 4: Train [Jul 2024 → Feb 2026]  → Test [Feb 2026 → Jul 2026]
                      ← expanding →
```

**Time-Split Validation (Expert Strategies):**
- RSM Swing, Manual Institutional: 50/50 time split
- Combined Swing: 60/40 time split

**Capital-Constrained Simulation (ORB):**
- ₹50,000 starting capital
- 1 position at a time (sequential)
- Max 5 entries per day
- 1% risk per trade (₹500)

**Cost Model applied to ALL trades:**
- STT: 0.025%
- Brokerage: ₹20 per trade
- Slippage: 0.05%
- GST: 18% on brokerage
- NSE/SEBI exchange fees

### 6.2 ML Opening Breakout — Walk-Forward Results

| Fold | Train Rows | Test Days | Trades | WR | Net PnL |
|:----:|:----------:|:---------:|:-----:|:--:|:-------:|
| 1 | 120,439 | 5 months | 100 | 91.0% | +₹54,298 |
| 2 | 241,214 | 5 months | 100 | 83.0% | +₹45,588 |
| 3 | 363,405 | 5 months | 103 | 85.4% | +₹49,620 |
| 4 | 488,430 | 5 months | 101 | 84.2% | +₹48,518 |
| **Total** | — | **486 days** | **404** | **85.9%** | **+₹198,026** |

**Interpretation:** The model achieves >83% win rate in every single fold across 1.5 years of unseen future data. This is strong evidence the edge is real and not due to overfitting.

### 6.3 ML Standalone — Walk-Forward Results

| Metric | Value |
|--------|-------|
| Walk-forward OOS trades | 71 |
| Net PnL | +₹49,985 |
| WR | 38% |
| Folds positive | 4/4 |

### 6.4 RSM Swing — Time-Split Results

| Metric | Full (76 syms) | Pruned (8 syms) |
|--------|:--------------:|:---------------:|
| Trades | 5,410 | 1,161 |
| Net PnL | −₹105,940 | **+₹104,027** |
| WR | — | 38.5% |
| Profitable syms | — | 8/8 |

**Key insight:** The full universe was net-negative due to cost drag. After OOS pruning symbols that weren't cost-positive in both time halves, the remaining 8 symbols turned net-positive.

### 6.5 Combined Swing — Time-Split Results

| Metric | Full (64 syms) | Pruned (17 syms) |
|--------|:--------------:|:----------------:|
| Trades | 4,504 | 1,211 |
| Net PnL | −₹10,095 | **+₹162,382** |
| WR | — | 45.6% |
| Profitable syms | — | 17/17 |

### 6.6 Manual Institutional — Time-Split Results

| Metric | Full (73 syms) | Pruned (9+5 syms) |
|--------|:--------------:|:-----------------:|
| Trades | 3,798 | 446 |
| Net PnL | −₹35,694 | **+₹68,469** |
| WR | — | 12.9% |

### 6.7 Daily Trend Breakout — Cross-Section Results

| Metric | Value |
|--------|-------|
| Trades | 6,903 (171 symbols traded of 500) |
| Net PnL | **+₹1,992,944** |
| WR | 48.3% |
| AvgR | +0.501 |
| Top symbols | MAZDOCK +₹106k, BSE +₹101k, RVNL +₹76k |
| Profitable symbols | 114 (108 with ≥10 trades) |

### 6.8 Combined Portfolio

| Strategy | Trades | Net PnL | WR |
|----------|:-----:|:-------:|:--:|
| Daily Trend Breakout | 6,903 | +₹1,992,944 | 48.3% |
| ML Opening Breakout | 404 | +₹198,026 | 85.9% |
| Combined Swing | 1,211 | +₹162,382 | 45.6% |
| RSM Swing | 1,161 | +₹104,027 | 38.5% |
| Manual Institutional | 446 | +₹68,469 | 12.9% |
| ML Standalone | 71 | +₹49,985 | 38.0% |
| **Total** | **10,196** | **+₹2,575,833** | — |

---

## Chapter 7: Challenges

### 7.1 The Cost Trap

**Problem:** Early backtests showed impressive gross returns. When transaction costs (STT, brokerage, slippage) were included, most strategies flipped to net-negative. This is because many strategies have high frequency (hundreds of trades) and tight stop losses — costs per trade can be 0.5-1R.

**Solution:** OOS prune protocol — each symbol must be net-positive in BOTH halves of the time-split validation. This removed 84% of symbols but turned every strategy from net-negative to net-positive.

### 7.2 Data Limitations

**Problem:** yfinance (initial data source) only provides 60 days of 15-minute data. This is insufficient for training ML models.

**Solution:** Switched to the Upstox V3 API, which provides native 729-day history for any timeframe. This enabled a full 2-year dataset.

### 7.3 In-Sample vs Out-of-Sample Gap

**Problem:** ML Standalone showed 84% training accuracy but only 38% OOS win rate — classic overfitting.

**Solution:** 
1. Walk-forward validation protocol (4 folds, expanding window)
2. Fixed decision thresholds (not chosen based on test performance)
3. Feature set finalized before any test set evaluation

### 7.4 Market Regime Dependence

**Problem:** The original LONG-only model performed well in bull markets but failed in corrections.

**Solution:** Symmetric LONG+SHORT training — the model scores both directions at every bar and takes the best one that clears the threshold. This is regime-robust by design.

### 7.5 Loss Streaks and Psychological Pressure

**Problem:** An 8/9 loss streak caused concern about strategy viability.

**Solution:** Backtest analysis revealed:
- Maximum loss streak in 6,903 trades: 26
- Average loss streak: 5.5
- 8-loss streak probability: 1.68% (expected ~116 times in full dataset)

This was normal variance, not strategy failure. Data-driven analysis prevented premature abandonment.

---

## Chapter 8: Conclusion

### 8.1 Key Learnings

**Technical:**
- Feature engineering is prompt engineering — designing the right input vector for an AI model
- Walk-forward validation is essential for time-series AI models
- Costs must be included in model evaluation from day one
- Production AI systems need crash recovery, logging, and monitoring

**Professional:**
- Every claim must be backed by data
- Iterate systematically: hypothesis → test → measure → decide
- A negative result (strategy doesn't work) is still valuable data

### 8.2 Connection to Generative AI Internship

This project directly applies Generative AI concepts learned during the internship:
- **Prompt Engineering** → Feature vector design
- **LLM text generation** → XGBoost decision generation
- **Chain-of-thought reasoning** → Factor-based expert system evaluation
- **Model validation** → Walk-forward OOS testing
- **Temperature/selectivity** → Decision threshold tuning

### 8.3 Future Scope

1. **Multi-timeframe ML model:** Combine 5m, 15m, and 1d features into a single model
2. **Reinforcement learning:** Train an agent to optimize position sizing
3. **Broader universe:** Extend beyond NSE 500 to include futures and options
4. **Risk management:** Dynamic position sizing based on market volatility
5. **Real-money deployment:** Once sufficient OOS confidence is established

### 8.4 Closing

The AI-Powered Multi-Strategy Trading System demonstrates that Generative AI concepts — prompt engineering, model validation, and decision generation — can be applied beyond text to build production-grade automated decision systems. The system runs live today, processing 500+ Indian stocks every 5 minutes with 6 parallel AI strategies, all validated out-of-sample before deployment.
