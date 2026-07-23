# TRADE_CANDIDATE_MODEL.md

# Trade Candidate Model

Version: 1.0

Status: Frozen

Layer: Trade Construction

---

# 1. Purpose

A Trade Candidate represents a fully specified trading proposal produced from a Portfolio Decision.

It transforms capital allocation decisions into executable trade specifications.

It performs no execution.

It performs no broker interaction.

It performs no portfolio optimization.

---

# 2. Definition

A Trade Candidate is an immutable semantic object representing a proposed trade generated from a Portfolio Decision.

It specifies all information required for execution planning while remaining independent of any broker or exchange.

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

Execution Plan

↓

Orders

↓

Positions

---

# 4. Purpose

Portfolio Decision answers

"How should capital be allocated?"

Trade Candidate answers

"What exactly should be traded?"

Trade Construction separates investment decisions from execution mechanics.

---

# 5. Inputs

A Trade Candidate is produced from

• Portfolio Decision

Optionally

• Current Market Prices

• Tick Size

• Instrument Metadata

• Risk Parameters

Version 1 ignores optional inputs.

---

# 6. Outputs

Every Trade Candidate produces

Trade Direction

Capital Allocation

Entry Specification

Exit Specification

Risk Parameters

Execution Metadata

This output becomes the input to the Execution Planning layer.

---

# 7. Required Fields

Every Trade Candidate shall contain

Identity

Trade ID

Creation Time

Instrument

Symbol

Timeframe

Trade

Direction

Capital Allocation

Position Size

Entry Price

Stop Loss

Take Profit

Risk Reward Ratio

Execution

Order Type

Validity

Explanation

Trade Rationale

---

# 8. Trade Direction

Version 1 defines

LONG

SHORT

WAIT

WAIT indicates that no executable trade should be constructed.

---

# 9. Entry Specification

Version 1 allows

UNKNOWN

Future versions may introduce

Market Entry

Limit Entry

Stop Entry

Algorithmic Entry

Entry logic remains independent of execution.

---

# 10. Exit Specification

Version 1 allows

UNKNOWN

Future versions may introduce

Fixed Target

Trailing Stop

Scaling

Time Exit

Volatility Exit

---

# 11. Position Size

Position Size represents the quantity to be traded.

Version 1 may use placeholder values.

Future versions shall compute position size using

Risk Budget

Volatility

Stop Distance

Portfolio Constraints

---

# 12. Risk Reward Ratio

Version 1 allows

UNKNOWN

Future versions compute

Reward ÷ Risk

using explicit entry, stop, and target prices.

---

# 13. Order Type

Version 1 defines

UNKNOWN

Future versions may include

MARKET

LIMIT

STOP

STOP_LIMIT

ICEBERG

TWAP

VWAP

---

# 14. Trade Candidate Validity

A Trade Candidate is valid only if

• A Portfolio Decision exists.

• Trade Direction is explicit.

• Capital Allocation is explicit.

• Position Size is explicit.

• Trade Rationale exists.

---

# 15. Lifecycle

Constructed

↓

Validated

↓

Consumed by Execution Planning

↓

Archived

Trade Candidates are immutable.

New information produces a new Trade Candidate.

---

# 16. Relationship to Portfolio Decision

Portfolio Decision determines

Capital Allocation.

Trade Candidate determines

Trade Specification.

Trade Construction never changes Portfolio Decisions.

---

# 17. Relationship to Execution Plan

Trade Candidate

↓

Execution Plan

Execution Planning determines

Broker Instructions

Routing

Timing

Order Management

Trade Candidate intentionally excludes execution mechanics.

---

# 18. Design Principles

The Trade Candidate Model shall remain

Immutable

Theory-independent

Execution-independent

Explainable

Deterministic

Testable

Versionable

Broker-independent

---

# 19. Responsibility

The Trade Candidate Model

does not reason about markets.

does not optimize portfolios.

does not execute trades.

does not communicate with brokers.

It exists solely to represent a standardized trade proposal ready for execution planning.

---

# 20. Relationship to Other Objects

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

Trade Outcome

↓

Performance

---

# 21. Architectural Principle

Market Thesis explains the market.

Opportunity proposes an action.

Opportunity Assessment evaluates the action.

Opportunity Ranking prioritizes competing actions.

Portfolio Decision allocates capital.

Trade Candidate specifies the proposed trade.

Execution Planning determines how the trade will be executed.

Execution realizes the trade.

Each object owns exactly one stage of autonomous trading intelligence.

---

# 22. Future Extensions

Future versions may introduce

• Dynamic Position Sizing

• ATR-based Stops

• Multi-Target Exits

• Partial Scaling

• Volatility-based Entries

• Smart Order Routing

• Broker-specific Instructions

• Algorithmic Execution

These enhancements shall extend Trade Construction without modifying the Trade Candidate contract.