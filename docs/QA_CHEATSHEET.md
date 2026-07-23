# Anticipated Q&A — Presentation Defense

---

## Q1: How is this Generative AI?

The system uses XGBoost classifiers that **generate** decisions (LONG/SHORT/NONE) from raw input features — the same pipeline as an LLM generating text from a prompt. Feature engineering is prompt engineering, the model produces probability scores like a language model produces token probabilities, and decision thresholds control selectivity like temperature.

---

## Q2: Is it making money live?

The system runs in **paper trading mode** on Upstox — simulated trades with real market data but no real money. Of the 6 strategies, only 3 have fired trades so far (RSM Swing, Combined Swing, Daily Trend). The remaining 3 are extremely selective and haven't triggered yet. The backtest results are net of all costs and validated OOS, but **paper trading results should not be confused with real performance**.

---

## Q3: Why 6 strategies? Why not just one?

Single strategies fail in regime shifts. An ensemble of 6 strategies — spanning 3 timeframes (5m, 15m, 1d), 2 AI approaches (ML + expert systems), and both directions (LONG and both) — diversifies risk. When one strategy struggles (e.g., RSM in range-bound markets), another may thrive (e.g., Daily Trend in trending markets). The combined portfolio is more robust than any single strategy.

---

## Q4: What is walk-forward validation?

It's the gold standard for time-series ML validation. You train on past data, then test on a completely unseen future period. Then you expand the training window to include that test period, and test on the next future period. Repeat 4 times. The model is **never evaluated on data it has seen during training**. This prevents the #1 cause of failure in trading systems: backtest overfitting.

---

## Q5: How much capital is needed?

All backtests use a ₹50,000 capital model with 1% risk per trade (₹500). The system is designed to scale linearly — ₹1,00,000 would produce approximately 2× the PnL. The ORB walk-forward simulation explicitly tested with ₹50k, sequential positions, and a 5/day cap to ensure realistic results.

---

## Q6: Can it lose money all of a sudden?

Yes. Markets change regimes. The system had an 8/9 loss streak during paper trading. Analysis showed:
- The worst backtest loss streak was 26 trades
- Average loss streak: 5.5
- 8-loss streak probability: 1.68% (expected ~116 times in 6,903 trades)

**Losses are normal variance, not strategy failure.** The system is designed for positive expectancy over many trades, not to win every trade.

---

## Q7: How do you prevent overfitting?

Four defenses:
1. **Walk-forward validation** — never test on training data
2. **Fixed thresholds** — thresholds are set a-priori, not optimized on test data
3. **Out-of-sample prune** — symbols must be net-positive in BOTH halves of time-split validation
4. **Cost-inclusive backtest** — all results include STT, brokerage, slippage, and taxes

---

## Q8: What happens if the market changes permanently?

The models are designed to be **retrained monthly** through the walk-forward process. New data extends the training window, so the model adapts to changing conditions. The expanding-window approach means the model always trains on the most recent data. However, if the market fundamentally changes (e.g., switch to 24×7 trading), the feature set and model architecture would need redesign.

---

## Q9: Is this ready for real money?

The **strategies themselves** have been rigorously validated OOS. However, there are important caveats:
- Paper trading has only run for a few weeks
- 3 of 6 strategies haven't fired a trade yet live
- Real execution (slippage, fills, latency) may differ from backtest assumptions
- **Recommendation:** At least 3-6 more months of paper trading before considering real deployment

---

## Q10: Why did you build 3 ML strategies AND 3 expert strategies?

The ML strategies capture patterns too subtle for rules (e.g., the ORB model learned that a specific combination of gap size + opening range + first-bar volume predicts direction). The expert strategies encode trader intuition that is hard to learn from data (e.g., the 11-factor Manual engine replicates years of discretionary experience).

They complement each other: ML finds edges the rule designer didn't know existed; rules capture edges that the data doesn't have enough examples of.

---

## Q11: How long did this take?

The internship was 2 months. The system was built iteratively in phases:
- Phase A-E: Strategy design and initial backtesting (weeks 1-3)
- Phases 18-27: OOS validation, cost analysis, symbol pruning (weeks 4-6)
- Phases 31-37: ML strategies, live deployment, paper trading (weeks 7-8)

---

## Q12: What's the most important lesson?

**Costs matter more than accuracy.** A model with 84% training accuracy can be net-negative after costs. The real edge is not in the pattern — it's in whether the pattern survives STT, brokerage, and slippage. Always evaluate AI models in their real operating environment.
