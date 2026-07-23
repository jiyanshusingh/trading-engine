# Executive Summary

## AI-Powered Multi-Strategy Trading System

During a 2-month internship at **Digitaaztrans Technologies Pvt. Ltd.** in the Generative AI division, I developed an **AI-powered multi-strategy trading system** that applies Generative AI concepts — prompt engineering, model validation, and decision generation — to automate stock market analysis and trading decisions.

### Problem
Retail traders manually analyze hundreds of charts daily, leading to inconsistent, emotional, and time-consuming decisions. No systematic validation process exists to measure whether a strategy actually works.

### Solution
A production-grade system running **6 parallel AI strategies** across 5-minute, 15-minute, and daily timeframes on 500+ Indian stocks:

- **3 ML-based strategies** (XGBoost classifiers): ML Standalone (35 features), ML Opening Breakout (33 features), ML Filter — these *generate* trading decisions from raw market features, analogous to how an LLM generates text from prompts
- **3 rule-based expert systems**: RSM Swing (7 factors), Combined Swing (7 factors + day windows), Manual Institutional (11 factors), Daily Trend Breakout (6 factors + Donchian breakout)

### Validation
Every strategy was validated **out-of-sample before deployment**:
- **ML Opening Breakout walk-forward** (4 folds, 486 days): 404 OOS trades, **85.9% win rate**, positive in ALL 4 folds
- **Capital-constrained simulation** (₹50k, 5/day cap): **+₹198,026 net PnL**
- All 6 strategies combined: **10,196 trades, +₹2,575,833 net PnL** (₹50k capital model)

### Architecture
A live system running on the Upstox platform, fetching real-time data every 5 minutes, computing 33-35 features per bar per symbol, evaluating all 6 strategies, and executing paper trades autonomously with crash recovery.

### Key Learning
Feature engineering is prompt engineering — the same skills of designing the right input for an AI model apply whether the model generates text or trading decisions. The most critical lesson: **cost-awareness trumps accuracy** — a model with 84% accuracy can be net-negative after transaction costs.

---

*Internship Project — Digitaaztrans Technologies Pvt. Ltd. | July 2026*
