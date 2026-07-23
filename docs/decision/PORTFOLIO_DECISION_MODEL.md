# PORTFOLIO_DECISION_MODEL.md

# Portfolio Decision Model

Version: 1.0

Status: Frozen

Layer: Portfolio Intelligence

---

# 1. Purpose

A Portfolio Decision represents the final capital allocation decision produced from one or more Opportunity Rankings.

It determines where available capital should be allocated.

It performs no execution.

It performs no order generation.

It performs no broker interaction.

---

# 2. Definition

A Portfolio Decision is an immutable semantic object representing the allocation of available capital across one or more ranked Opportunities under explicit objectives and constraints.

It is the final output of the Portfolio Intelligence layer.

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

Trade Candidate

↓

Execution

---

# 4. Purpose

Portfolio Decision separates

Opportunity Prioritization

from

Trade Construction.

Ranking answers

"Which Opportunities are best?"

Portfolio Decision answers

"How should capital be distributed among them?"

---

# 5. Inputs

A Portfolio Decision consumes

• One or more Opportunity Rankings

• Portfolio Objectives

• Portfolio Constraints

Optionally

• Existing Positions

• Portfolio Exposure

• Available Cash

• Risk Budget

• Diversification Rules

Version 1 ignores optional inputs.

---

# 6. Outputs

A Portfolio Decision produces

Selected Opportunities

Capital Allocation

Cash Reserve

Allocation Method

Decision Rationale

This output becomes the input to Trade Candidate Generation.

---

# 7. Required Fields

Every Portfolio Decision shall contain

Identity

Decision ID

Creation Time

Decision Scope

Selected Opportunity References

Allocation

Capital Allocation

Cash Reserve

Total Allocated

Allocation Method

Portfolio Constraints

Explanation

Decision Rationale

---

# 8. Allocation

Allocation specifies the percentage of available capital assigned to each selected Opportunity.

Example

Opportunity A

40%

Opportunity B

35%

Opportunity C

25%

The sum of all allocations plus Cash Reserve shall equal 100%.

---

# 9. Cash Reserve

Cash Reserve represents intentionally unallocated capital.

Version 1 may allocate

0%

Future versions may maintain dynamic cash reserves.

---

# 10. Allocation Methods

Version 1

Fixed Weight

Future versions may introduce

Equal Weight

Risk Parity

Kelly Criterion

Volatility Scaling

Conviction Weighting

Machine Learning Allocation

The architecture shall remain unchanged.

---

# 11. Portfolio Constraints

Version 1 assumes all constraints are satisfied.

Future constraints may include

Maximum Position Size

Maximum Sector Exposure

Maximum Correlation

Maximum Portfolio Risk

Liquidity Limits

Cash Reserve Targets

---

# 12. Portfolio Decision Validity

A Portfolio Decision is valid only if

• At least one Opportunity Ranking exists.

• Capital Allocation is explicit.

• Total Allocated is explicit.

• Allocation Method is explicit.

• Decision Rationale exists.

---

# 13. Lifecycle

Constructed

↓

Validated

↓

Consumed by Trade Candidate Generation

↓

Archived

Portfolio Decisions are immutable.

New market information produces a new Portfolio Decision.

---

# 14. Relationship to Opportunity Ranking

Opportunity Ranking determines relative priority.

Portfolio Decision determines capital allocation.

Portfolio Decision never changes Rankings.

---

# 15. Relationship to Trade Candidate

Portfolio Decision

↓

Trade Candidate

Trade Candidates specify

Entry Logic

Exit Logic

Risk Parameters

Execution Constraints

Portfolio Decision intentionally excludes these details.

---

# 16. Design Principles

The Portfolio Decision Model shall remain

Immutable

Theory-independent

Portfolio-aware

Execution-independent

Explainable

Deterministic

Testable

Versionable

---

# 17. Responsibility

The Portfolio Decision Model

does not generate Opportunities.

does not rank Opportunities.

does not generate orders.

does not execute trades.

It exists solely to represent the final allocation of capital across selected Opportunities.

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

Trade Candidate

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

Opportunity Assessment evaluates each Opportunity independently.

Opportunity Ranking compares Opportunities.

Portfolio Decision allocates capital across ranked Opportunities.

Trade Candidate specifies execution.

Execution realizes the selected decisions.

Each object represents exactly one stage of autonomous decision making.

---

# 20. Future Extensions

Future versions may incorporate

• Dynamic Position Sizing

• Portfolio Optimization

• Risk Parity

• Kelly Allocation

• Correlation Adjustment

• Sector Rotation

• Exposure Limits

• Reinforcement Learning Allocation

These enhancements shall refine allocation behavior without changing the Portfolio Decision contract.