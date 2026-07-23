# MARKET_THESIS_MODEL.md

# Market Thesis Model

## Purpose

This document defines the Market Thesis, the primary reasoning artifact
produced by the Decision Layer.

A Market Thesis explains the market.

It does not decide what action should be taken.

A Market Thesis exists to provide an explicit, falsifiable,
evidence-supported explanation of the current market situation that can
later be transformed into a Decision Thesis.

The Market Thesis forms the contract between objective market knowledge
and autonomous decision making.

---

# 1. Definition

A Market Thesis is an immutable, evidence-supported explanation of the
current market situation that predicts one or more plausible future
structural evolutions under explicit assumptions.

A Market Thesis is:

- explainable
- falsifiable
- evidence-based
- objective-driven
- theory-dependent

A Market Thesis is not:

- a trade
- an order
- a position
- an execution plan
- a portfolio decision

---

# 2. Purpose

The purpose of a Market Thesis is to answer one question:

> What explanation of the current market is best justified by the
> available objective evidence?

The output is an explanation.

Not an action.

---

# 3. Position in the Architecture

Observation History

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

The Market Thesis separates market understanding from decision making.

---

# 4. Inputs

A Market Thesis may be constructed only from:

• Canonical Market Model

• Explicit Objectives

• Applicable Constraints

Reasoning Models may interpret facts differently.

They may never modify objective facts.

---

# 5. Outputs

A Market Thesis produces:

• Market explanation

• Expected structural evolution

• Supporting evidence

• Counter evidence

• Assumptions

• Uncertainty estimate

• Invalidation conditions

These outputs are consumed by downstream decision components.

---

# 6. Required Components

Every Market Thesis shall contain the following information.

## Identity

Unique Thesis Identifier

Creation Timestamp

Reasoning Model

Model Version

Theory

---

## Scope

Symbol

Timeframe

Market Regime

Session

Applicable Objectives

The Scope defines where the thesis is valid.

---

## Central Claim

The Market Thesis shall contain exactly one primary explanatory claim.

Examples

Bullish continuation is currently the best-supported explanation.

Bearish structural reversal is currently the best-supported explanation.

Range continuation is currently the best-supported explanation.

The Central Claim explains the market.

It does not recommend an action.

---

## Supporting Evidence

Every claim must identify objective evidence supporting it.

Evidence must originate from the Canonical Market Model.

Examples

Protected Swings

Expansions

Origin Regions

Fair Value Gaps

Order Blocks

Structure Events

No evidence may be invented by the Reasoning Model.

---

## Counter Evidence

Every Market Thesis must explicitly acknowledge evidence that weakens
its central claim.

Ignoring contradictory evidence is prohibited.

Counter evidence improves explainability and learning.

---

## Assumptions

Every thesis depends upon explicit assumptions.

Examples

Higher timeframe structure remains valid.

No major news event before execution.

Liquidity remains unchanged.

Assumptions are not facts.

They are conditions under which the thesis is expected to remain valid.

---

## Expected Structural Evolution

The thesis predicts future structural behaviour.

Examples

Continuation toward external liquidity.

Expansion continuation.

Structural reversal.

Range persistence.

The prediction concerns market structure.

It does not define execution.

---

## Uncertainty

Every Market Thesis must explicitly communicate uncertainty.

Uncertainty represents how strongly the available evidence supports the
central claim.

Uncertainty is not certainty.

It represents remaining ambiguity after reasoning.

---

## Invalidation

Every thesis must define objective invalidation conditions.

Examples

Protected Swing failure.

Confirmed CHOCH.

Structural reversal.

Invalidation enables learning.

---

# 7. Validity Axioms

Every Market Thesis must satisfy all of the following axioms.

## Axiom 1

Evidence Based

Every claim must be supported by objective facts.

---

## Axiom 2

Explainable

Every conclusion must identify supporting evidence.

---

## Axiom 3

Falsifiable

Every thesis must define objective invalidation conditions.

---

## Axiom 4

Internally Consistent

The thesis must not contain contradictory claims.

---

## Axiom 5

Scope Limited

The thesis is valid only within its declared scope.

---

## Axiom 6

Immutable

Once created, a Market Thesis never changes.

Future information creates a new thesis.

---

## Axiom 7

Independently Testable

A thesis must be evaluable without requiring downstream decisions.

---

# 8. Relationship to Other Objects

Canonical Market Model

Contains objective facts.

Market Thesis

Contains an evidence-supported explanation.

Decision Thesis

Selects one action using the Market Thesis.

Execution Plan

Defines how the chosen action will be executed.

Order

Communicates instructions to a broker.

Position

Represents live market exposure.

Outcome

Represents realized market results.

These objects must never be conflated.

---

# 9. Lifecycle

Observation History

↓

Canonical Market Model

↓

Reasoning Model

↓

Market Thesis

The Market Thesis is immutable.

It is never modified.

It may produce zero, one, or many downstream Decision Theses.

---

# 10. Evaluation

A Market Thesis is evaluated independently of trading outcomes.

Reasoning Quality considers:

• completeness

• coherence

• explainability

• evidence quality

• falsifiability

Predictive Quality considers:

• calibration

• structural prediction accuracy

• robustness

Reasoning Quality and Predictive Quality are independent.

---

# 11. Design Principles

The Market Thesis exists to explain the market.

It never:

• allocates capital

• chooses actions

• creates orders

• sizes positions

• communicates with brokers

Its sole responsibility is to produce the best justified explanation of
the current market situation.

---

# 12. Theory Independence

The architecture is independent of market theory.

Different Reasoning Models may construct different Market Theses from
the same Canonical Market Model.

Examples

ICT

Wyckoff

Trend Following

Mean Reversion

Machine Learning

Hybrid Models

The Market Thesis contract remains unchanged.

---

# 13. Theory 1.0 Freeze

Theory 1.0 freezes the Market Thesis Model.

A Market Thesis is the immutable explanation produced by a Reasoning
Model from objective market facts.

It serves as the formal interface between market understanding and
decision making.

Every downstream decision must be justifiable by one or more Market
Theses.

The quality of the autonomous trading system depends upon the quality of
its Market Theses rather than the complexity of its implementation.