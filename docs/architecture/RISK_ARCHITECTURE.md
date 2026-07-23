# Risk Architecture

## Purpose

This document defines the Risk Layer for Theory 1.0.

The Risk Layer consumes approved TradeCandidates and determines whether
they should become executable trades.

Risk is responsible for protecting capital.

Risk never constructs market structure.

Risk never generates trading opportunities.

---

# 1. Architectural Goal

The Risk Layer answers one question:

> Given this trading opportunity, what level of risk is acceptable?

Possible outcomes include:

- approve trade
- reject trade
- reduce position size
- increase position size
- postpone execution

---

# 2. Position in the Architecture

Live Market
        │
        ▼
ObservationHistory
        │
        ▼
Semantic Construction
        │
        ▼
CanonicalMarketModel
        │
        ▼
Market Interpretation
        │
        ▼
Strategy
        │
        ▼
TradeCandidate
        │
        ▼
Trade Candidate Evaluation
        │
        ▼
Risk
        │
        ▼
Execution
        │
        ▼
Broker

---

# 3. Responsibilities

Risk is responsible for:

- capital preservation
- position sizing
- exposure control
- stop-loss validation
- portfolio risk evaluation
- approving or rejecting trades

Risk is not responsible for:

- market interpretation
- strategy generation
- ontology construction
- broker communication

---

# 4. Input

Risk consumes:

ApprovedTradeCandidate

The Risk Layer never consumes ontology directly.

Market knowledge has already been interpreted.

---

# 5. Output

Risk produces:

RiskDecision

Example:

Approved

Position Size

Maximum Loss

Stop Distance

Capital Allocation

Risk Score

The RiskDecision becomes the input to Execution.

---

# 6. Capital Preservation

Capital preservation is the primary responsibility of the Risk Layer.

The system should always prioritize long-term survival over short-term
profit.

---

# 7. Position Sizing

Risk determines:

- quantity
- leverage
- exposure
- capital allocation

Position sizing is independent of strategy quality.

---

# 8. Exposure Control

Risk manages:

- maximum portfolio exposure
- maximum symbol exposure
- sector exposure
- correlation
- concurrent positions

Exposure management is separate from strategy.

---

# 9. Trade Approval

Every approved TradeCandidate must satisfy risk constraints.

Examples:

Maximum loss

Minimum reward-risk ratio

Available capital

Portfolio exposure

If any constraint fails, the trade is rejected.

---

# 10. Stop Loss Validation

Risk validates:

- stop placement
- maximum acceptable loss
- stop distance
- volatility compatibility

Risk may reject a candidate with an unsuitable stop.

---

# 11. Portfolio Awareness

Risk evaluates every trade within the context of the entire portfolio.

Examples:

Too many long positions

Too much banking exposure

High correlation

Insufficient diversification

Risk protects the portfolio, not individual trades.

---

# 12. Explainability

Every RiskDecision must explain itself.

Example

Approved

Reasons

✓ Risk within limits

✓ Exposure acceptable

✓ Capital available

✓ Portfolio balanced

Rejected

Reasons

✗ Daily loss limit reached

✗ Sector exposure exceeded

✗ Position size below minimum

---

# 13. Separation of Responsibilities

Ontology

Produces market facts.

Market Interpretation

Produces market understanding.

Strategy

Produces TradeCandidates.

Risk

Determines acceptable exposure.

Execution

Places orders.

Broker

Communicates with exchanges.

---

# 14. Dependency Rules

ObservationHistory

↓

Semantic Construction

↓

CanonicalMarketModel

↓

Market Interpretation

↓

Strategy

↓

TradeCandidate

↓

Trade Candidate Evaluation

↓

Risk

↓

Execution

↓

Broker

Reverse dependencies are prohibited.

---

# 15. Design Principles

Risk must be:

- deterministic
- explainable
- independent
- conservative
- testable
- portfolio-aware

Risk consumes approved candidates.

Risk never changes strategy outputs.

---

# 16. Future Extensions

Theory 1.0 permits:

- volatility-adjusted sizing
- Kelly-based sizing
- adaptive risk
- portfolio optimization
- dynamic exposure management
- AI-assisted risk

These extensions must preserve the architectural boundary.

---

# 17. Theory 1.0 Freeze

Theory 1.0 freezes the responsibilities of the Risk Layer.

Risk exists to protect capital.

Risk evaluates approved trading opportunities.

Risk never:

- constructs ontology
- interprets market structure
- generates strategies
- communicates with brokers

The Risk Layer determines how much should be risked, never what the
market objectively is.