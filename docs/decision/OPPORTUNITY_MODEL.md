# OPPORTUNITY_MODEL.md

# Opportunity Model

Version: 1.0

Status: Frozen

Layer: Decision Intelligence

---

# 1. Purpose

An Opportunity represents a justified candidate for action produced from one or more Market Theses.

It is the first object in the Decision Intelligence layer.

A Market Thesis explains the market.

An Opportunity answers whether the market currently justifies considering an action.

The Opportunity itself is **not a trade**.

It is a decision candidate.

---

# 2. Definition

An Opportunity is an immutable semantic object representing a justified, actionable candidate produced from one or more Market Theses under explicit objectives and constraints.

An Opportunity performs no reasoning.

It contains no execution details.

It contains no broker-specific information.

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

Opportunity

↓

Trade Candidate

↓

Portfolio Decision

↓

Execution

---

# 4. Purpose

The Opportunity layer separates

Market Understanding

from

Decision Making.

A Market Thesis may exist without producing any Opportunity.

Examples

Valid Thesis

↓

No attractive opportunity

↓

Wait

This separation prevents every thesis from becoming a trade.

---

# 5. Inputs

An Opportunity is constructed from:

• One or more Market Theses

• Portfolio Context

• Objectives

• Constraints

Optionally

• Existing Positions

• Exposure Limits

• Risk Budget

---

# 6. Outputs

An Opportunity produces a standardized decision candidate.

Examples

Long Opportunity

Short Opportunity

Wait

Reduce Exposure

Increase Exposure

Close Position

Only later does a Portfolio Decision select among competing Opportunities.

---

# 7. Required Fields

Every Opportunity must contain

Identity

Opportunity ID

Creation Time

Reasoning Source

Scope

Symbol

Timeframe

Market Regime

Applicable Session

Decision

Opportunity Type

Direction

Justification

Supporting Market Thesis References

Supporting Evidence Summary

Counter Evidence Summary

Objectives

Constraints

Assessment

Priority

Evidence Quality

Reasoning Quality

Expected Structural Evolution

Risk Context

Portfolio Dependencies

Assumptions

Invalidation

---

# 8. Opportunity Types

Version 1

LONG

SHORT

WAIT

Future versions may add

REDUCE

EXIT

HEDGE

REBALANCE

The architecture shall not assume trading is always opening a position.

---

# 9. Opportunity Lifecycle

Constructed

↓

Evaluated

↓

Ranked

↓

Selected

↓

Converted into Trade Candidate

↓

Rejected

An Opportunity is immutable.

Evaluation never mutates an Opportunity.

New information creates a new Opportunity.

---

# 10. Opportunity Validity

An Opportunity is valid only if

• At least one supporting Market Thesis exists.

• Supporting reasoning is explainable.

• Supporting reasoning is falsifiable.

• Evidence Quality is available.

• Reasoning Quality is available.

• Portfolio objectives are explicit.

• Constraints are explicit.

---

# 11. Opportunity Ranking

The Opportunity itself contains no ranking logic.

Ranking is performed by the Opportunity Evaluation layer.

This separation allows multiple evaluation strategies without modifying the Opportunity model.

---

# 12. Opportunity vs Market Thesis

Market Thesis answers

"What does the market currently justify believing?"

Opportunity answers

"Given that understanding, should the engine consider acting?"

Therefore

Multiple Opportunities may originate from the same Market Thesis.

Example

Bullish Thesis

↓

Long Opportunity

Bullish Thesis

↓

Wait

Different portfolio contexts may produce different Opportunities from identical Market Theses.

---

# 13. Opportunity vs Trade Candidate

Opportunity

Represents

A justified candidate for action.

Trade Candidate

Represents

A fully specified executable trading proposal.

Trade Candidates include

Entry Logic

Exit Logic

Risk Parameters

Execution Constraints

The Opportunity intentionally excludes these details.

---

# 14. Design Principles

The Opportunity Model shall remain

Immutable

Theory-independent

Explainable

Falsifiable

Portfolio-aware

Execution-independent

Testable

Versionable

---

# 15. Responsibility

The Opportunity Model performs no reasoning.

It performs no ranking.

It performs no optimization.

It performs no execution.

It is solely the standardized representation of a justified candidate for action produced by the Decision Intelligence layer.

---

# 16. Relationship to Other Objects

Canonical Market Model

↓

Market Thesis

↓

Opportunity

↓

Trade Candidate

↓

Portfolio Decision

↓

Execution Plan

↓

Orders

↓

Position

↓

Outcome

---

# 17. Architectural Principle

A Market Thesis explains the market.

An Opportunity proposes a justified candidate for action.

A Trade Candidate specifies how that action could be executed.

A Portfolio Decision selects which Trade Candidates receive capital.

Execution realizes the selected decisions.

Each object reduces a distinct uncertainty.

No object performs the responsibility of another.