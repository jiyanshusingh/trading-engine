# ICT_REASONING_MODEL.md

# ICT Reasoning Model

## Purpose

This document defines the Theory 1.0 ICT Reasoning Model.

The ICT Reasoning Model is the first implementation of the Reasoning Model
Contract.

Its responsibility is to transform an objective Canonical Market Model
into one or more justified Market Theses.

The model explains the market.

It does not decide how capital should be allocated.

It does not execute trades.

---

# 1. Definition

The ICT Reasoning Model is an evidence-based reasoning model that
constructs explainable Market Theses using the ICT market structure
ontology.

The model operates exclusively on objective market facts contained in the
Canonical Market Model.

The model never creates or modifies market facts.

---

# 2. Objective

The ICT Reasoning Model answers one question.

> Given the current objective market facts, what explanation of the
> market is currently best justified according to ICT principles?

The output is one or more Market Theses.

The output is not a trading decision.

---

# 3. Position in the Architecture

Observation History

↓

Semantic Construction

↓

Canonical Market Model

↓

ICT Reasoning Model

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

The ICT Reasoning Model forms the boundary between market understanding
and autonomous decision making.

---

# 4. Inputs

The ICT Reasoning Model consumes only objective information.

## Mandatory Inputs

• Canonical Market Model

## Optional Inputs

• Objectives

• Operational Constraints

• Portfolio Context

Optional inputs influence reasoning priorities but never modify market
facts.

---

# 5. Market Knowledge

The ICT Reasoning Model reasons using ontology objects.

Examples include

• Swings

• Protected Swings

• Structure Events

• Expansions

• Origin Regions

• Fair Value Gaps

• Order Blocks

No additional market facts may be introduced.

---

# 6. Core Principles

## Principle 1

Facts precede reasoning.

Reasoning never alters facts.

---

## Principle 2

Every conclusion must be supported by objective evidence.

---

## Principle 3

Contradictory evidence must always be acknowledged.

---

## Principle 4

Every Market Thesis must be falsifiable.

---

## Principle 5

Reasoning explains.

Decision making decides.

Execution executes.

Responsibilities remain independent.

---

## Principle 6

Multiple Market Theses may exist simultaneously.

Markets rarely admit only one explanation.

---

# 7. Reasoning Process

The ICT Reasoning Model performs six reasoning stages.

---

## Stage 1

Recognize Structure

Objective

Understand the current structural organization.

Evaluate

• Swings

• Structure Events

• Expansions

Outputs

Objective structural observations.

No conclusions are produced.

---

## Stage 2

Construct Structural Context

Objective

Understand the larger market context.

Evaluate

• Expansion continuity

• Origin Region integrity

• Protected Swing integrity

Outputs

Contextual understanding of current structure.

---

## Stage 3

Collect Supporting Evidence

Objective

Identify evidence supporting possible market explanations.

Examples

Bullish continuation

Supporting evidence

• Active Expansion

• Protected Swing respected

• Bullish Order Block respected

• Bullish Fair Value Gap respected

Evidence remains objective.

---

## Stage 4

Collect Counter Evidence

Objective

Identify evidence that weakens each explanation.

Examples

Bullish continuation

Counter evidence

• Nearby opposing liquidity

• Bearish Order Block

• Protected Swing weakness

Every explanation must explicitly acknowledge contradictory evidence.

---

## Stage 5

Construct Market Theses

Objective

Transform evidence into one or more justified Market Theses.

Each thesis contains

• Central Claim

• Supporting Evidence

• Counter Evidence

• Assumptions

• Expected Structural Evolution

• Invalidation

• Uncertainty

Multiple Market Theses are permitted.

---

## Stage 6

Rank Market Theses

Objective

Determine which Market Thesis is currently best supported.

Ranking expresses explanatory preference.

It never represents certainty.

---

# 8. Explainability

Every Market Thesis produced by the ICT Reasoning Model shall answer:

What is happening?

Why is this explanation justified?

What evidence supports it?

What evidence weakens it?

What assumptions are required?

What observations would invalidate it?

---

# 9. Falsifiability

Every Market Thesis must define objective invalidation.

Examples

• Protected Swing failure

• Confirmed CHOCH

• Expansion termination

• Origin Region failure

Learning depends upon explicit invalidation.

---

# 10. Uncertainty

Markets are inherently uncertain.

The ICT Reasoning Model does not predict certainty.

It identifies the explanation currently best supported by available
evidence.

Future observations may strengthen, weaken, or invalidate any thesis.

---

# 11. Scope

The ICT Reasoning Model explains markets.

It never

• allocates capital

• sizes positions

• selects orders

• determines execution

• communicates with brokers

These responsibilities belong to downstream components.

---

# 12. Evaluation

The ICT Reasoning Model is evaluated independently of execution.

Reasoning Quality

• Explainability

• Completeness

• Internal Consistency

• Evidence Quality

• Falsifiability

Predictive Quality

• Structural Prediction Accuracy

• Calibration

• Robustness

• Stability across market regimes

Execution profitability is evaluated separately.

---

# 13. Extensibility

The platform supports multiple Reasoning Models.

Examples

• ICT

• Wyckoff

• Trend Following

• Mean Reversion

• Statistical Models

• Machine Learning

Each implements the same Reasoning Model Contract.

Only the reasoning changes.

The architecture remains stable.

---

# 14. Theory 1.0 Freeze

Theory 1.0 freezes the ICT Reasoning Model.

The ICT Reasoning Model is an evidence-based reasoning system that
transforms objective market facts into one or more justified Market
Theses.

It never recommends actions.

It never allocates capital.

It never executes trades.

Its sole responsibility is to explain the market according to ICT
principles.

The quality of the ICT Reasoning Model is measured by the quality,
explainability, falsifiability, coherence, and predictive performance of
the Market Theses it constructs.

Future improvements shall evolve the reasoning algorithm while preserving
the Reasoning Model Contract and the Market Thesis Contract.