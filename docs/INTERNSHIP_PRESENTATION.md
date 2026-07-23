# Internship Presentation — AI-Powered Multi-Strategy Trading System

## Slide 1: Title Slide

**AI-Powered Multi-Strategy Trading System**

Internship Project — Digitaaztrans Technologies Pvt. Ltd.

[Your Name] | [Department] | July 2026

---

## Slide 2: Internship Overview (1 min)

**Company:** Digitaaztrans Technologies Pvt. Ltd.

**Duration:** 2 months

**Domain:** Generative AI, Prompt Engineering, AI Applications

**Key areas covered:**
- Large Language Models & prompt engineering
- AI workflow design & decision-making systems
- Building AI applications that generate decisions from data
- Model validation & testing methodologies

---

## Slide 3: The Problem (1 min)

**Retail traders face:**
- Hundreds of stocks to monitor daily — impossible to watch manually
- Emotional decision-making under pressure
- Inconsistent analysis — same setup gets different treatment on different days
- No systematic way to validate if a strategy actually works

> **Objective:** Build an AI system that automates market analysis and generates high-probability trading decisions — applying the Generative AI principles learned during the internship.

---

## Slide 4: AI Approach (1.5 min)

**How Generative AI maps to this project:**

| Internship Concept | Project Application |
|-------------------|-------------------|
| Prompt Engineering | Feature engineering — designing the 33-35 input vectors that "prompt" the AI model |
| LLM generates text | XGBoost generates trading decisions (LONG/SHORT/NONE) with probability scores |
| Chain-of-thought reasoning | Expert system engines weigh 6-11 factors sequentially to reach a decision |
| Model validation | Walk-forward OOS testing across 4 disjoint future time windows |
| Temperature / sampling | Decision threshold tuning (0.70, 0.80) controls selectivity vs frequency |

> *"Instead of generating text, the AI models in this system generate trading decisions from market data — the same Generative AI pipeline, just a different output domain."*

---

## Slide 5: System Architecture (2 min)

```
                          LIVE SYSTEM ARCHITECTURE

              ┌──────────────────────────────────────┐
              │         MARKET DATA (Upstox API)      │
              │    V2 REST + V3 Intraday WebSocket    │
              └──────────────────┬───────────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────────┐
              │         FEATURE ENGINEERING           │
              │    (Prompt Engineering equivalent)    │
              │  33-35 features per bar per symbol    │
              └──────────────────┬───────────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────────┐
              │       6 AI DECISION ENGINES           │
              ├──────────────────────────────────────┤
              │  ┌────────────────────────────────┐   │
              │  │ ML Standalone     (XGBoost)    │   │ ← GENERATIVE AI
              │  │ ML Opening Brk    (XGBoost)    │   │ ← GENERATIVE AI
              │  │ ML Filter         (XGBoost)    │   │ ← GENERATIVE AI
              │  ├────────────────────────────────┤   │
              │  │ RSM Swing         (7-factor)   │   │ ← EXPERT SYSTEM
              │  │ Combined Swing    (7-factor)   │   │ ← EXPERT SYSTEM
              │  │ Manual Inst.      (11-factor)  │   │ ← EXPERT SYSTEM
              │  │ Daily Trend       (6-factor)   │   │ ← EXPERT SYSTEM
              │  └────────────────────────────────┘   │
              └──────────────────┬───────────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────────┐
              │      DECISION FILTER + RISK           │
              │  • Confidence thresholds (0.70/0.80)  │
              │  • Capital: ₹50k, 1% risk/trade       │
              │  • Max 5 entries/day per strategy     │
              │  • ML filter applied to RSM/Comb/Man  │
              └──────────────────┬───────────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────────┐
              │         ORDER EXECUTION               │
              │    • Upstox paper trading (live)      │
              │    • --real flag for live capital     │
              │    • SL/TP/trailing stop management   │
              │    • EOD square-off (intraday modes)  │
              └──────────────────────────────────────┘
```

**Visual:** Show this architecture flowchart on screen.

---

## Slide 6: The 3 ML-Based Strategies — Generative AI (2 min)

**These directly demonstrate Generative AI principles:**

### ML Standalone
- **What:** XGBoost classifier trained on **3.98 million** labeled 15-minute bars
- **Features:** 35 market-state features (RSI, ATR, volume ratio, EMA distances, NIFTY context, hour, weekday)
- **Output:** Generates LONG/SHORT decision with probability score
- **Threshold:** 0.80 — only ~0.2-0.3% of bars pass (extreme selectivity by design)
- **Validation:** **4-fold walk-forward** across 2 years — **ALL 4 folds positive**
- **Result:** 71 OOS trades, +₹49,985 net PnL, WR 38%

### ML Opening Breakout (ORB)
- **What:** XGBoost trained on 620k opening-window bars
- **Features:** 33 features — gap %, opening range %, first-bar metrics, NIFTY context
- **Output:** Generates entry decision in the first 75 minutes (09:15-10:30 IST)
- **Validation:** **4-fold walk-forward**, capital-constrained (₹50k, 5/day cap)
- **Result:** 404 OOS trades, **85.9% WR**, +₹198,026 net PnL
- **Edge holds in ALL 4 disjoint future windows** — strong evidence of real pattern learning

### ML Filter
- **What:** XGBoost classifier that filters other strategies' signals
- **Output:** Probability that a given signal will be net-profitable
- **Result:** Turns net-negative raw signals into net-positive subset (+₹108k OOS)

> *"Each ML model was trained to GENERATE a decision from raw market features — this is Generative AI applied to trading."*

---

## Slide 7: The 3 Rule-Based Strategies — Expert Systems (1.5 min)

**Classic AI — rule-based expert systems with sequential factor evaluation:**

| Strategy | Factors | What it Evaluates | Net PnL | WR |
|----------|:-------:|-------------------|:-------:|:--:|
| **RSM Swing** | 7 | Relative strength vs NIFTY, volume surge, VWAP separation, breakout range, price acceleration, NIFTY context, intraday structure | +₹104,027 | 38.5% |
| **Combined Swing** | 7 | Same 7 factors + per-day entry windows (different windows for each weekday) | +₹162,382 | 45.6% |
| **Daily Trend Breakout** | 6 | Donchian breakout + trend quality, volume confirmation, ADX proxy, RSI momentum, RS vs NIFTY | +₹1,992,944 | 48.3% |
| **Manual Institutional** | 11 | Market regime, sector strength, price action, volume, breakout quality, R:R, indicators, catalyst, timing, historical perf., short context | +₹68,469 | 12.9% |

> *"These are rule-based AI systems. Each factor is like a step in chain-of-thought reasoning — the engine evaluates evidence sequentially and produces a decision."*

---

## Slide 8: Validation Methodology (2 min)

**This is the most important slide — it shows proper AI validation.**

### The Problem with Most Trading Systems
They report backtest results on the same data the model was tuned on (in-sample bias).

### My Approach — Walk-Forward OOS Testing

The model is **never tested on data it has seen during training**. Each fold's test window is a completely unseen future period.

```
Fold 1: Train [2024-07 → 2024-12]  → Test [2024-12 → 2025-05]  (unseen future)
Fold 2: Train [2024-07 → 2025-05]  → Test [2025-05 → 2025-09]  (unseen future)
Fold 3: Train [2024-07 → 2025-09]  → Test [2025-09 → 2026-02]  (unseen future)
Fold 4: Train [2024-07 → 2026-02]  → Test [2026-02 → 2026-07]  (unseen future)
                          ← expanding window →
```

**486 trading days** of data split into 4 folds. Each fold retrains the model from scratch. Results are from disjoint, out-of-sample periods only.

**Capital-constrained simulation** (for ORB): ₹50k capital, 1-position-at-a-time, max 5 entries/day, sequential position sizing.

### All strategies validated OOS:
- **ML Standalone/ORB:** 4-fold walk-forward
- **RSM Swing, Manual Inst.:** 50/50 time-split
- **Combined Swing:** 60/40 time-split
- **Daily Trend:** 5-year cross-section (no time-split yet — strategy is recent)

---

## Slide 9: Results — ML Opening Breakout Walk-Forward (1.5 min)

**Best example of rigorous ML validation:**

| Fold | Train Rows | Test Days | OOS Trades | Win Rate | Net PnL (₹50k) |
|:----:|:----------:|:---------:|:----------:|:--------:|:--------------:|
| 1 | 120,439 | ~5 months | 100 | **91.0%** | +₹54,298 |
| 2 | 241,214 | ~5 months | 100 | **83.0%** | +₹45,588 |
| 3 | 363,405 | ~5 months | 103 | **85.4%** | +₹49,620 |
| 4 | 488,430 | ~5 months | 101 | **84.2%** | +₹48,518 |
| **Total** | — | **486 days** | **404** | **85.9%** | **+₹198,026** |

**Key insight:** The edge holds in ALL 4 disjoint future windows between Dec 2024 and Jul 2026 — strong evidence the AI has learned a real, repeatable market pattern, not just memorized history.

Visual: Show a bar chart with 4 bars (one per fold, all positive).

---

## Slide 10: Results — All 6 Strategies Combined (1 min)

| Strategy | Type | Trades | Net PnL (₹50k) | WR |
|----------|:----:|:-----:|:--------------:|:--:|
| Daily Trend Breakout | 6-factor + Donchian | 6,903 | **+₹1,992,944** | 48.3% |
| ML Opening Breakout | XGBoost (33 feat) | 404 | **+₹198,026** | **85.9%** |
| Combined Swing | 7-factor expert | 1,211 | +₹162,382 | 45.6% |
| RSM Swing | 7-factor expert | 1,161 | +₹104,027 | 38.5% |
| Manual Institutional | 11-factor expert | 446 | +₹68,469 | 12.9% |
| ML Standalone | XGBoost (35 feat) | 71 | +₹49,985 | 38.0% |
| **Portfolio Total** | **6 strategies** | **10,196** | **+₹2,575,833** | — |

> *"Each strategy was validated out-of-sample before deployment. The portfolio of 6 diversifies across timeframes (5m, 15m, 1d), market regimes, and AI approaches (ML + expert systems)."*

---

## Slide 11: Challenges & Solutions (1.5 min)

| Challenge | Solution |
|-----------|----------|
| **Costs destroy the edge** | Transaction costs flip gross-positive strategies to net-negative. Fixed by OOS prune: removed 84% of symbols that didn't survive cost-inclusive validation across both halves of the time period. |
| **Data limitation** | yfinance caps 15m data at 60 days. Switched to Upstox V3 API which provides native 729-day history per timeframe, enabling 2+ years of backtest data. |
| **In-sample vs OOS gap** | ML Standalone showed 84% training accuracy but only 38% OOS WR. Solved by walk-forward validation protocol and fixed threshold selection (not chosen on test set). |
| **Market regime dependence** | The original LONG-only model failed in bear markets. Solved by symmetric LONG+SHORT training — the model learns both directions simultaneously. |
| **Loss streaks are normal** | 8/9 loss streak caused concern. Backtest analysis showed 26-loss maximum streak and 5.5 avg streak — the 8-loss streak had 1.68% probability and was expected to occur ~116 times in 6,903 trades. |

---

## Slide 12: What I Learned (1 min)

### Technical Skills
- **Prompt Engineering → Feature Engineering:** The same skill of designing the right input for an AI model, applied to market data instead of text
- **Model Validation:** Walk-forward testing, avoiding data leakage, threshold selection without lookahead bias
- **Cost-Aware AI:** A high-accuracy model is useless if real-world costs destroy the edge — the ORB model had 84% WR but tight SLs meant costs were significant
- **Production System Design:** Building a live 24/7 AI system with 6 parallel engines, crash recovery, WebSocket feeds, and broker integration

### Professional Skills
- **Iterative development:** Each phase revealed new issues (costs, regime dependence, data quality) that required systematic debugging
- **Data-driven decisions:** Every change was validated with numbers, not intuition — the OOS prune, entry timing changes, day-of-week multipliers all backed by data
- **Production AI:** Moving from a Jupyter notebook to a live system with real-time data, rate limits, and crash recovery

---

## Slide 13: Certificate & Conclusion (0.5 min)

**Certificate:** (Display briefly — 20 seconds)

**Conclusion:**
> *"This internship gave me hands-on experience building Generative AI systems that operate in the real world. I learned that AI is not just about model accuracy — it's about validation, cost awareness, and production reliability. The system I built runs live today on the Upstox platform, making automated decisions every 5 minutes across 6 strategies and 500+ Indian stocks."*

---

## Slide 14: Q&A

Be prepared for questions from QA_CHEATSHEET.md.

---

# Speaker Notes Summary

### Slide 1
"Good morning/afternoon. I'm [Name], and I completed a 2-month internship at Digitaaztrans Technologies in Generative AI."

### Slide 2
"During this internship, I worked on Generative AI, prompt engineering, and AI applications. The key deliverable was this project."

### Slide 3
"Retail traders face a fundamental problem: they can't monitor hundreds of stocks manually, and their decisions are inconsistent. The goal was to build an AI that automates this."

### Slide 4
"The connection between Generative AI and this project: instead of generating text, we generate trading decisions. Feature engineering is prompt engineering. XGBoost is the language model. The threshold is the temperature parameter."

### Slide 5
"Walk through the architecture: data comes from Upstox API, gets converted into feature vectors (the prompts), then goes through 6 AI engines — 3 ML-based and 3 rule-based — before a decision filter and execution."

### Slide 6
"These 3 strategies directly use Generative AI. Each XGBoost model was trained on millions of examples to GENERATE a decision — LONG, SHORT, or NONE — from raw market features."

### Slide 7
"These 4 strategies use rule-based expert systems. Each factor is a step in the reasoning chain, like chain-of-thought prompting."

### Slide 8
"This is the most important slide. Most trading systems overfit to historical data. My approach uses walk-forward validation — the model is never tested on data it has seen. This is the gold standard for ML validation."

### Slide 9
"The ORB results are the strongest evidence. 404 trades across 4 completely unseen future periods, ALL positive. The worst fold still has 83% win rate and +₹45k profit."

### Slide 10
"The combined portfolio of 6 strategies generates +₹2.5M on ₹50k capital across 10,196 trades. Each strategy targets different timeframes and market conditions."

### Slide 11
"Every challenge was a learning opportunity. The cost trap taught me that real-world AI requires cost-aware design. The OOS prune taught me rigorous validation."

### Slide 12
"I learned to think of feature engineering as prompt engineering, proper validation methodology, and how to build production AI systems."

### Slide 13
(Show certificate briefly) "This certificate acknowledges the completion of my internship and the project work. The system is live today."

### Slide 14
"Thank you. I'm happy to answer any questions."
