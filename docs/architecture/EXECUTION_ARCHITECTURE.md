# Execution Architecture

## Purpose

This document defines the architecture of the Execution Layer for
Theory 1.0.

The Execution Layer consumes the immutable semantic ontology and
transforms objective market knowledge into executable trading decisions.

Execution never constructs market structure.

Execution never modifies ontology.

Execution only interprets and acts upon existing semantic knowledge.

---

# 1. Architectural Goal

The Execution Layer answers one question:

> Given the current market understanding, what should the trading system
> do?

Possible actions include:

- Wait
- Generate a trade candidate
- Enter a position
- Manage an existing position
- Exit a position

---

# 2. Execution Pipeline

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
Trade Candidate Generation
        │
        ▼
Opportunity Ranking
        │
        ▼
Risk Evaluation
        │
        ▼
Execution Decision
        │
        ▼
Broker Execution
        │
        ▼
Trade Monitoring
        │
        ▼
Performance Evaluation

---

# 3. Responsibilities

The Execution Layer is responsible for:

- interpreting semantic facts
- identifying trading opportunities
- ranking opportunities
- evaluating risk
- generating executable decisions
- monitoring open positions
- recording execution outcomes

The Execution Layer is not responsible for:

- detecting swings
- confirming BOS
- constructing Order Blocks
- creating semantic ontology

---

# 4. Inputs

Execution consumes exactly one market representation.

CanonicalMarketModel

This model contains:

- ObservationHistory
- Swings
- StructureEvents
- ProtectedSwings
- Expansions
- OriginRegions
- FairValueGaps
- OrderBlocks

Execution must not consume raw semantic collections directly.

Correct:

ExecutionEngine(model)

Incorrect:

ExecutionEngine(
    swings,
    expansions,
    order_blocks,
)

---

# 5. Execution Stages

Execution is divided into independent stages.

Stage 1

Market Interpretation

↓

Stage 2

Trade Candidate Generation

↓

Stage 3

Opportunity Ranking

↓

Stage 4

Risk Evaluation

↓

Stage 5

Execution Decision

↓

Stage 6

Trade Monitoring

↓

Stage 7

Performance Evaluation

Every stage has exactly one responsibility.

---

# 6. Market Interpretation

Purpose

Interpret objective market facts.

Produces:

MarketInterpretation

Examples:

- Market Bias
- Trend Strength
- Structural Alignment
- Liquidity Context
- Confidence

Interpretation is theory-dependent.

---

# 7. Trade Candidate Generation

Purpose

Generate possible trading opportunities.

Produces:

TradeCandidate

A TradeCandidate represents a hypothesis.

It is not an executed trade.

Example:

LONG

Entry

Stop

Target

Confidence

Reasons

---

# 8. Opportunity Ranking

Purpose

Compare every TradeCandidate generated across all monitored symbols.

Produces:

RankedTradeCandidates

Ranking may consider:

- confidence
- expected reward
- expected risk
- structural quality
- portfolio impact

Ranking never places trades.

---

# 9. Risk Evaluation

Purpose

Determine whether a candidate should be traded.

Produces:

RiskDecision

Examples:

Position Size

Maximum Loss

Stop Distance

Capital Allocation

Risk never modifies market interpretation.

---

# 10. Execution Decision

Purpose

Convert approved TradeCandidates into executable broker actions.

Produces:

ExecutionDecision

Possible actions:

WAIT

ENTER_LONG

ENTER_SHORT

EXIT

MODIFY_POSITION

Execution Decisions never calculate market structure.

---

# 11. Broker Execution

Purpose

Communicate with the broker.

Responsibilities:

- place orders
- modify orders
- cancel orders
- synchronize positions

Broker adapters must contain no market logic.

---

# 12. Trade Monitoring

Purpose

Monitor active positions.

Examples:

- stop hit
- target reached
- trailing stop
- partial exits
- timeout

Monitoring never changes ontology.

---

# 13. Performance Evaluation

Purpose

Measure system performance.

Examples:

Win Rate

Expectancy

Maximum Drawdown

Average Risk Reward

Profit Factor

Every executed trade should be evaluated.

---

# 14. Explainability

Every execution decision should be explainable.

Example:

LONG

Reasons:

✓ Bullish Expansion

✓ Protected Swing intact

✓ Origin Region respected

✓ Fair Value Gap active

✓ Order Block confirmed

Execution should never produce unexplained decisions.

---

# 15. Theory Independence

Different theories may interpret the same ontology differently.

Example

CanonicalMarketModel

↓

ICT Interpretation

↓

Trade Candidates

CanonicalMarketModel

↓

Wyckoff Interpretation

↓

Trade Candidates

The ontology remains unchanged.

Only interpretation changes.

---

# 16. Separation of Responsibilities

Semantic Construction

Answers:

What objectively exists?

Execution

Answers:

What should be done?

Risk

Answers:

How much should be risked?

Broker

Answers:

How should orders be placed?

Portfolio

Answers:

How should capital be distributed?

Each layer has exactly one responsibility.

---

# 17. Dependency Rules

Dependency direction is strictly one-way.

ObservationHistory

↓

Semantic Construction

↓

CanonicalMarketModel

↓

Market Interpretation

↓

Trade Candidate Generation

↓

Risk Evaluation

↓

Execution

↓

Broker

↓

Performance Evaluation

Reverse dependencies are prohibited.

---

# 18. Design Principles

Execution must be:

- deterministic
- explainable
- modular
- testable
- theory-independent
- broker-independent

Execution should consume ontology.

Execution should never extend ontology.

---

# 19. Future Extensions

Theory 1.0 permits future additions such as:

- multiple execution engines
- multiple theories
- portfolio optimization
- adaptive risk
- reinforcement learning
- execution analytics

These extensions must preserve the execution architecture defined in this
document.

---

# 20. Theory 1.0 Execution Freeze

Theory 1.0 freezes the execution architecture.

Future development may improve:

- interpretation
- trade generation
- ranking
- risk
- execution

while preserving:

- immutable ontology
- semantic dependency graph
- execution pipeline
- separation of responsibilities

Execution consumes market knowledge.

Execution does not create market knowledge.