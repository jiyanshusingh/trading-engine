# EXECUTION_PLAN_MODEL.md

# Execution Plan Model

Version: 1.0

Status: Frozen

Layer: Execution Planning

---

# 1. Purpose

An Execution Plan represents a fully specified execution strategy produced from a Trade Candidate.

It transforms a proposed trade into an executable instruction.

It performs no broker communication.

It performs no order submission.

It performs no position management.

---

# 2. Definition

An Execution Plan is an immutable semantic object representing how a Trade Candidate should be executed.

It specifies execution details while remaining independent of any broker or exchange.

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

↓

Trade Outcome

---

# 4. Purpose

Trade Candidate answers

"What should be traded?"

Execution Plan answers

"How should the trade be executed?"

Execution Planning separates trade construction from execution mechanics.

---

# 5. Inputs

An Execution Plan consumes

• Trade Candidate

Optionally

• Current Market Price

• Exchange Metadata

• Tick Size

• Liquidity Information

• Slippage Model

• Broker Capabilities

Version 1 ignores optional inputs.

---

# 6. Outputs

Every Execution Plan produces

Execution Method

Order Type

Entry Instruction

Exit Instruction

Execution Constraints

Broker Instructions

This output becomes the input to Order Management.

---

# 7. Required Fields

Every Execution Plan shall contain

Identity

Execution Plan ID

Creation Time

Trade Reference

Trade ID

Execution

Execution Method

Order Type

Entry Price

Stop Loss

Take Profit

Validity

Time In Force

Risk Controls

Maximum Slippage

Partial Fill Allowed

Explanation

Execution Rationale

---

# 8. Execution Method

Version 1 defines

IMMEDIATE

Future versions may introduce

SMART_ROUTING

VWAP

TWAP

ICEBERG

PASSIVE

AGGRESSIVE

---

# 9. Order Type

Version 1 defines

MARKET

LIMIT

STOP

UNKNOWN

Future versions may include

STOP_LIMIT

ICEBERG

PEGGED

ALGORITHMIC

---

# 10. Validity

Version 1 defines

DAY

GTC

UNKNOWN

Future versions may support

IOC

FOK

GTD

---

# 11. Slippage

Version 1 allows

UNKNOWN

Future versions may include

Maximum Slippage

Expected Slippage

Liquidity Adjustment

---

# 12. Partial Fill Policy

Version 1 defines

TRUE

FALSE

Future versions may support

Minimum Fill Size

Execution Windows

---

# 13. Execution Plan Validity

An Execution Plan is valid only if

• A Trade Candidate exists.

• Order Type is explicit.

• Execution Method is explicit.

• Execution Rationale exists.

---

# 14. Lifecycle

Constructed

↓

Validated

↓

Consumed by Order Management

↓

Archived

Execution Plans are immutable.

New market information produces a new Execution Plan.

---

# 15. Relationship to Trade Candidate

Trade Candidate specifies

Trade Intent.

Execution Plan specifies

Execution Strategy.

Execution Planning never changes Trade Candidates.

---

# 16. Relationship to Orders

Execution Plan

↓

Orders

Order Management converts Execution Plans into broker-specific orders.

Execution Plan remains broker-independent.

---

# 17. Design Principles

The Execution Plan Model shall remain

Immutable

Theory-independent

Broker-independent

Exchange-independent

Explainable

Deterministic

Testable

Versionable

---

# 18. Responsibility

The Execution Plan Model

does not reason about markets.

does not allocate capital.

does not construct trades.

does not communicate with brokers.

does not manage positions.

It exists solely to represent how a Trade Candidate should be executed.

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

# 20. Architectural Principle

Market Thesis explains the market.

Opportunity proposes an action.

Opportunity Assessment evaluates the action.

Opportunity Ranking prioritizes competing actions.

Portfolio Decision allocates capital.

Trade Candidate specifies the trade.

Execution Plan specifies execution.

Order Management communicates with brokers.

Positions represent executed trades.

Trade Outcomes measure results.

Each object owns exactly one stage of autonomous trading.

---

# 21. Future Extensions

Future versions may introduce

• Smart Order Routing

• Dynamic Order Selection

• Liquidity-Aware Execution

• Broker Selection

• Multi-Exchange Routing

• Algorithmic Execution

• Execution Cost Models

• Adaptive Slippage Control

These enhancements shall extend execution behavior without modifying the Execution Plan contract.