# OPPORTUNITY_ASSESSMENT_MODEL.md

# Opportunity Assessment Model

Version: 1.0

Status: Frozen

Layer: Decision Intelligence

---

# 1. Purpose

An Opportunity Assessment is an immutable semantic object representing an independent evaluation of a single Opportunity.

It measures the attractiveness of an Opportunity under explicit objectives and constraints.

It performs no ranking.

It performs no capital allocation.

It performs no execution.

---

# 2. Definition

An Opportunity Assessment is a justified, explainable, and immutable evaluation of an Opportunity.

It summarizes whether an Opportunity is sufficiently attractive to proceed to the Opportunity Ranking stage.

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

The Opportunity Assessment layer separates

Opportunity Generation

from

Opportunity Comparison.

Every Opportunity is evaluated independently before competing against other Opportunities.

This ensures assessment remains objective and reusable.

---

# 5. Inputs

An Opportunity Assessment is produced from

• Opportunity

• Objectives

• Constraints

Optionally

• Portfolio Context

• Exposure Limits

• Risk Budget

Version 1 ignores optional inputs.

---

# 6. Outputs

An Opportunity Assessment produces

Assessment Level

Overall Score

Actionability

Objective Alignment

Constraint Satisfaction

Assessment Rationale

This output becomes the input to Opportunity Ranking.

---

# 7. Required Fields

Every Opportunity Assessment shall contain

Identity

Assessment ID

Creation Time

Opportunity Reference

Evaluation

Assessment Level

Overall Score

Actionable

Objective Alignment

Constraint Satisfaction

Reasoning

Assessment Rationale

Supporting Opportunity Reference

---

# 8. Assessment Levels

Version 1 defines

HIGH

MEDIUM

LOW

Future versions may introduce

VERY_HIGH

VERY_LOW

REJECTED

without changing the architecture.

---

# 9. Actionability

An Opportunity Assessment explicitly records whether the Opportunity is actionable.

Possible values

TRUE

FALSE

An Opportunity may exist while still being assessed as not actionable.

Example

WAIT Opportunity

↓

Actionable = FALSE

---

# 10. Objective Alignment

The assessment records whether the Opportunity satisfies the declared objectives.

Examples

Trend Following

Swing Trading

Capital Preservation

Version 1 evaluates this using deterministic rules.

---

# 11. Constraint Satisfaction

The assessment records whether the Opportunity satisfies explicit constraints.

Examples

Maximum Exposure

Maximum Risk

Trading Session

Portfolio Limits

Version 1 assumes all constraints are satisfied.

Future versions will evaluate them explicitly.

---

# 12. Overall Score

The Overall Score summarizes the attractiveness of the Opportunity.

Version 1

HIGH

80

MEDIUM

60

LOW

30

The score exists only for downstream ranking.

It shall not directly allocate capital.

---

# 13. Lifecycle

Constructed

↓

Validated

↓

Consumed by Opportunity Ranking

↓

Archived

Opportunity Assessments are immutable.

New information produces a new Assessment.

---

# 14. Assessment Validity

An Opportunity Assessment is valid only if

• A valid Opportunity exists.

• Assessment Level is explicit.

• Actionability is explicit.

• Overall Score is explicit.

• Supporting Opportunity Reference exists.

---

# 15. Relationship to Opportunity

Opportunity answers

"Should this action be considered?"

Opportunity Assessment answers

"How attractive is this Opportunity?"

The Opportunity remains unchanged.

Assessment never mutates the Opportunity.

---

# 16. Relationship to Opportunity Ranking

Opportunity Assessment

↓

Opportunity Ranking

Ranking compares multiple Opportunity Assessments.

Assessment never compares Opportunities.

This separation allows different ranking algorithms without changing assessment logic.

---

# 17. Design Principles

The Opportunity Assessment Model shall remain

Immutable

Theory-independent

Explainable

Deterministic

Testable

Versionable

Portfolio-independent

Execution-independent

---

# 18. Responsibility

The Opportunity Assessment Model

does not generate Opportunities.

does not compare Opportunities.

does not allocate capital.

does not execute trades.

It exists solely to provide a standardized evaluation of a single Opportunity.

---

# 19. Relationship to Other Objects

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

Position

↓

Outcome

---

# 20. Architectural Principle

Market Thesis explains the market.

Opportunity proposes a candidate action.

Opportunity Assessment evaluates that candidate independently.

Opportunity Ranking compares assessed Opportunities.

Portfolio Decision allocates capital.

Execution realizes the selected decisions.

Each object reduces a distinct uncertainty and shall not assume the responsibilities of another.