# REASONING_MODEL_CONTRACT.md

# Reasoning Model Contract

## Purpose

This document defines the permanent contract that every Reasoning Model
must satisfy within the Institutional Trading AI platform.

A Reasoning Model transforms objective market knowledge into one or more
Market Theses.

The contract is intentionally independent of any trading theory,
strategy, or implementation technique.

It enables multiple reasoning approaches (ICT, Wyckoff, Trend Following,
Machine Learning, Hybrid Models, etc.) to coexist while preserving a
stable system architecture.

---

# 1. Definition

A Reasoning Model is an autonomous reasoning component that evaluates the
Canonical Market Model under explicit objectives and constraints and
constructs one or more justified Market Theses.

A Reasoning Model is responsible for reasoning.

It is not responsible for:

- market observation
- semantic construction
- portfolio optimization
- execution planning
- broker communication
- learning
- performance evaluation

---

# 2. Architectural Position

Observation History

↓

Semantic Construction

↓

Canonical Market Model

↓

Reasoning Model

↓

Market Thesis

↓

Decision Thesis

↓

Execution Plan

↓

Execution

↓

Learning

Reasoning Models form the boundary between objective market knowledge
and autonomous decision making.

---

# 3. Architectural Responsibility

A Reasoning Model answers one question:

> Given the current market facts, explicit objectives, and operational
> constraints, what explanations of the market are currently justified?

It does not decide whether capital should be allocated.

It explains the market.

---

# 4. Inputs

Every Reasoning Model shall receive only the following inputs.

## Canonical Market Model

The immutable objective description of the market.

Contains facts only.

Never beliefs.

Never decisions.

---

## Objectives

Examples

- Capital Growth
- Capital Preservation
- Swing Trading
- Intraday Trading
- Trend Following
- Mean Reversion

Objectives define what the system is trying to optimize.

---

## Operational Constraints

Examples

- Trading session
- Liquidity requirements
- Regulatory limits
- Maximum holding period
- Maximum leverage

Constraints restrict possible reasoning.

---

## Optional Context

Additional context may be supplied when appropriate.

Examples

- Higher timeframe summaries
- Portfolio state
- Market regime
- External risk filters

Optional context must never alter objective market facts.

---

# 5. Outputs

A Reasoning Model produces zero, one, or many Market Theses.

Each Market Thesis must satisfy the Market Thesis Contract.

Reasoning Models never produce:

- orders
- execution plans
- positions
- portfolio allocations

---

# 6. Core Responsibilities

Every Reasoning Model shall:

1. Interpret objective market facts.

2. Construct justified explanations.

3. Explicitly acknowledge contradictory evidence.

4. Estimate remaining uncertainty.

5. Define objective invalidation conditions.

6. Preserve explainability.

7. Remain independent of execution.

---

# 7. Required Properties

Every Reasoning Model shall satisfy the following properties.

## Objectivity

Only Canonical Market Model facts may be used as evidence.

Reasoning Models never invent facts.

---

## Explainability

Every conclusion must identify supporting evidence.

No unexplained conclusions are permitted.

---

## Falsifiability

Every Market Thesis must define objective invalidation.

---

## Determinism

Given identical inputs and configuration,
the Reasoning Model shall produce identical outputs.

---

## Immutability

Reasoning Models never modify:

- Observation History
- Canonical Market Model
- Existing Market Theses

They only construct new Market Theses.

---

## Theory Isolation

Reasoning logic belongs exclusively inside the Reasoning Model.

The remainder of the architecture remains theory-independent.

---

# 8. Evidence Rules

Evidence must originate from upstream objective facts.

Examples

- Swings
- Protected Swings
- BOS
- CHOCH
- Expansions
- Origin Regions
- Fair Value Gaps
- Order Blocks

Evidence may be interpreted.

It may never be altered.

---

# 9. Multiple Market Theses

Markets may admit multiple plausible explanations.

Therefore a Reasoning Model may generate:

- zero theses
- one thesis
- multiple competing theses

Competing Market Theses are permitted.

The Reasoning Model is responsible for justifying each thesis
independently.

---

# 10. Ranking

A Reasoning Model may express preference among competing Market Theses.

Preference must always be justified.

Preference does not imply certainty.

It indicates relative explanatory support.

---

# 11. Assumptions

Every Market Thesis produced by the Reasoning Model must explicitly state
its assumptions.

Assumptions are not facts.

Assumptions describe conditions under which the reasoning remains valid.

---

# 12. Counter Evidence

Every Reasoning Model shall explicitly identify evidence that weakens its
own conclusions.

Ignoring contradictory evidence is prohibited.

Counter evidence improves:

- transparency
- calibration
- learning

---

# 13. Scope

Every Market Thesis must declare its scope.

Examples

- Symbol
- Timeframe
- Session
- Market Regime
- Strategy Objective

Reasoning must never be applied outside its declared scope.

---

# 14. Separation of Responsibilities

Reasoning Models explain.

Decision Engines choose.

Execution Planners execute.

Learning evaluates.

These responsibilities shall never overlap.

---

# 15. What a Reasoning Model Must Never Do

A Reasoning Model shall never:

- allocate capital
- size positions
- determine stop losses
- determine entry prices
- determine order types
- communicate with brokers
- modify historical data
- modify objective market facts

These belong to downstream components.

---

# 16. Extensibility

Every reasoning approach shall implement the same contract.

Examples

- ICT
- Wyckoff
- Trend Following
- Mean Reversion
- Statistical Models
- Machine Learning
- Hybrid Models

The architecture remains unchanged regardless of reasoning methodology.

---

# 17. Validation

A Reasoning Model shall be evaluated independently of execution.

Evaluation considers:

## Reasoning Quality

- Explainability
- Completeness
- Internal Consistency
- Falsifiability
- Evidence Usage

## Predictive Quality

- Structural Prediction Accuracy
- Calibration
- Robustness
- Stability Across Market Regimes

Execution performance is evaluated separately.

---

# 18. Versioning

Every Reasoning Model shall expose:

- Model Name
- Theory
- Version
- Configuration
- Creation Date

This enables reproducible research and controlled evolution.

---

# 19. Future Compatibility

This contract is intentionally stable.

Future innovations such as:

- Bayesian Models
- Machine Learning
- Reinforcement Learning
- Graph Reasoning
- Hybrid Systems

must integrate by implementing this contract rather than modifying the
platform architecture.

---

# 20. Theory 1.0 Freeze

Theory 1.0 freezes the Reasoning Model Contract.

A Reasoning Model is the only component responsible for transforming
objective market facts into justified Market Theses.

The quality of the autonomous trading system depends not on the number of
Reasoning Models, but on the quality, explainability, falsifiability,
and predictive performance of the Market Theses they construct.

The platform architecture remains stable while Reasoning Models evolve
through continuous research, validation, and empirical improvement.