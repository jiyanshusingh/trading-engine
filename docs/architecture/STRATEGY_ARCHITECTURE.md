# Strategy Architecture

## Purpose

This document defines the Strategy Layer for Theory 1.0.

The Strategy Layer consumes a MarketInterpretation and produces
explainable TradeCandidates.

Strategies do not execute trades.

Strategies generate trading hypotheses that may later be approved or
rejected by the Risk Layer.

---

# 1. Architectural Goal

The Strategy Layer answers one question:

> Given the current market interpretation, what trading opportunities
> exist?

The Strategy Layer never answers:

- How much capital should be used?
- Should the broker receive an order?
- How should the position be managed?

Those responsibilities belong to later layers.

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
Risk
        │
        ▼
Execution

---

# 3. Responsibilities

Strategy is responsible for:

- identifying trading opportunities
- generating TradeCandidates
- explaining why opportunities exist
- scoring opportunity quality

Strategy is not responsible for:

- market structure construction
- ontology
- risk management
- execution
- broker communication

---

# 4. Input

Strategy consumes exactly one object.

MarketInterpretation

Strategy never reconstructs market structure.

Strategy never recalculates ontology.

---

# 5. Output

Strategy produces immutable TradeCandidate objects.

A TradeCandidate is not a trade.

It represents a possible trading opportunity.

---

# 6. TradeCandidate

Every TradeCandidate should contain enough information for the Risk Layer
to evaluate it.

Example fields:

- symbol
- direction
- entry_price
- stop_loss
- target_price
- expected_reward
- confidence
- generated_timestamp
- reasoning

TradeCandidate objects must be immutable.

---

# 7. Strategy Philosophy

Strategies propose.

They never execute.

Multiple strategies may generate TradeCandidates simultaneously.

Example:

ICT Strategy

↓

TradeCandidate A

Wyckoff Strategy

↓

TradeCandidate B

Statistical Strategy

↓

TradeCandidate C

---

# 8. Explainability

Every TradeCandidate must explain itself.

Example:

LONG

Reasons

✓ Bullish Expansion

✓ Protected Swing intact

✓ Fair Value Gap respected

✓ Bullish Order Block

✓ Higher timeframe aligned

TradeCandidates should never be opaque.

---

# 9. Opportunity Scoring

Strategies should estimate opportunity quality.

Scoring may consider:

- structural quality
- liquidity quality
- trend alignment
- expected reward
- confidence

Scoring is not probability.

It is a ranking mechanism.

---

# 10. Multiple Strategies

The same MarketInterpretation may be consumed by many strategies.

Example:

CanonicalMarketModel

↓

MarketInterpretation

↓

ICT Strategy

↓

TradeCandidate

CanonicalMarketModel

↓

MarketInterpretation

↓

Wyckoff Strategy

↓

TradeCandidate

Strategies remain independent.

---

# 11. Trade Candidate Ranking

Strategies generate opportunities.

A separate Ranking component compares them.

Ranking responsibilities include:

- sorting candidates
- removing duplicates
- prioritizing opportunities
- selecting the strongest setups

Ranking never modifies candidates.

---

# 12. Separation of Responsibilities

Semantic Construction

Produces objective market facts.

Market Interpretation

Produces market understanding.

Strategy

Produces TradeCandidates.

Risk

Evaluates whether candidates should be traded.

Execution

Places broker orders.

Portfolio

Coordinates capital across multiple positions.

---

# 13. Dependency Rules

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

Risk

↓

Execution

↓

Broker

Reverse dependencies are prohibited.

---

# 14. Design Principles

Strategies must be:

- deterministic
- explainable
- modular
- testable
- replaceable
- independent

Strategies consume interpretation.

Strategies never modify ontology.

---

# 15. Future Extensions

Theory 1.0 permits:

- multiple strategies
- ensemble strategies
- statistical strategies
- AI-assisted strategies
- adaptive strategies

These extensions must preserve architectural boundaries.

---

# 16. Theory 1.0 Freeze

Theory 1.0 freezes the Strategy Layer.

Its purpose is to transform MarketInterpretation into explainable
TradeCandidates.

Strategies:

✓ propose opportunities

✓ explain opportunities

✓ score opportunities

Strategies never:

✗ execute trades

✗ size positions

✗ communicate with brokers

✗ construct market ontology

The Strategy Layer exists to generate high-quality trading hypotheses
that can be objectively evaluated by downstream components.