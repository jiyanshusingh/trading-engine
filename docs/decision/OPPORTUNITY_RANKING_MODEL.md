# OPPORTUNITY_RANKING_MODEL.md

# Opportunity Ranking Model

Version: 1.0

Status: Frozen

Layer: Decision Intelligence

---

# 1. Purpose

An Opportunity Ranking represents the relative ordering of one or more Opportunity Assessments.

Its purpose is to determine which assessed Opportunities should receive priority for downstream Portfolio Decision.

Opportunity Ranking performs no market reasoning.

Opportunity Ranking performs no portfolio allocation.

Opportunity Ranking performs no execution.

---

# 2. Definition

An Opportunity Ranking is an immutable semantic object representing the relative priority of a single Opportunity Assessment within a set of competing Opportunities.

Ranking always occurs after Opportunity Assessment.

Ranking never modifies an Opportunity.

Ranking never modifies an Opportunity Assessment.

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

Opportunity Generator

↓

Opportunity

↓

Opportunity Assessment

↓

Opportunity Ranking

↓

Portfolio Decision

↓

Execution

---

# 4. Purpose

Opportunity Assessment answers

"How attractive is this Opportunity?"

Opportunity Ranking answers

"Which Opportunity deserves higher priority?"

Ranking therefore compares Opportunities.

Assessment never compares Opportunities.

---

# 5. Inputs

An Opportunity Ranking consumes

• One or more Opportunity Assessments

Optionally

• Portfolio Context

• Existing Positions

• Sector Exposure

• Correlation

• Risk Budget

Version 1 ignores optional inputs.

---

# 6. Outputs

Every Opportunity Ranking produces

Ranking Position

Ranking Score

Ranking Rationale

Priority Classification

Portfolio Eligibility

This output becomes the input to Portfolio Decision.

---

# 7. Required Fields

Every Opportunity Ranking shall contain

Identity

Ranking ID

Creation Time

Assessment Reference

Ranking

Rank Position

Ranking Score

Priority

Portfolio Eligible

Explanation

Ranking Rationale

---

# 8. Ranking Position

Ranking Position is an ordinal value.

Example

Rank 1

Rank 2

Rank 3

Rank N

Rank Position shall be unique within a ranking session.

---

# 9. Ranking Score

Ranking Score represents the relative attractiveness of an Opportunity.

Version 1 uses deterministic scoring.

Future versions may use

Weighted scoring

Machine learning

Portfolio optimization

Bayesian ranking

Without changing the architecture.

---

# 10. Priority Levels

Version 1 defines

HIGH

MEDIUM

LOW

Priority indicates downstream importance.

Priority does not allocate capital.

---

# 11. Portfolio Eligibility

Ranking explicitly records whether an Opportunity is eligible for Portfolio Decision.

Possible values

TRUE

FALSE

Eligibility does not imply allocation.

Portfolio Decision remains responsible for capital allocation.

---

# 12. Ranking Validity

A Ranking is valid only if

• A valid Opportunity Assessment exists.

• Rank Position is assigned.

• Ranking Score is assigned.

• Portfolio Eligibility is explicit.

• Ranking Rationale exists.

---

# 13. Lifecycle

Constructed

↓

Validated

↓

Consumed by Portfolio Decision

↓

Archived

Rankings are immutable.

New market information produces a new Ranking.

---

# 14. Relationship to Opportunity Assessment

Opportunity Assessment evaluates one Opportunity.

Opportunity Ranking compares many Opportunity Assessments.

Assessment remains independent.

Ranking introduces relative comparison.

---

# 15. Relationship to Portfolio Decision

Opportunity Ranking

↓

Portfolio Decision

Portfolio Decision allocates capital using

Rank

Risk

Exposure

Constraints

Objectives

Portfolio Decision shall never modify Rankings.

---

# 16. Design Principles

The Opportunity Ranking Model shall remain

Immutable

Theory-independent

Explainable

Deterministic

Testable

Versionable

Portfolio-aware

Execution-independent

---

# 17. Responsibility

The Opportunity Ranking Model

does not generate Opportunities.

does not assess Opportunities.

does not allocate capital.

does not execute trades.

It exists solely to represent the relative priority of assessed Opportunities.

---

# 18. Relationship to Other Objects

Canonical Market Model

↓

Market Thesis

↓

Opportunity

↓

Opportunity Assessment

↓

Opportunity Ranking

↓

Portfolio Decision

↓

Execution Plan

↓

Orders

↓

Positions

↓

Performance

---

# 19. Architectural Principle

Market Thesis explains the market.

Opportunity proposes a candidate action.

Opportunity Assessment evaluates each candidate independently.

Opportunity Ranking compares assessed candidates.

Portfolio Decision allocates capital.

Execution realizes the selected decisions.

Each object represents a distinct stage of decision making and shall not assume the responsibilities of another.

---

# 20. Future Extensions

Future versions may incorporate

• Multi-timeframe consensus

• Cross-asset competition

• Portfolio diversification

• Sector allocation

• Correlation penalties

• Volatility normalization

• Dynamic conviction weighting

These enhancements shall refine ranking behavior without altering the Opportunity Ranking contract.