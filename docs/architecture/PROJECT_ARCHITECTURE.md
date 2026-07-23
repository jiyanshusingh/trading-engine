# Project Architecture

## Purpose

This document defines the overall architecture of the Institutional
Trading AI project.

It describes the major architectural layers, their responsibilities,
their dependencies, and how they interact to build an autonomous
trading system.

The project is organized around a strict separation between:

- market knowledge
- trading decisions
- execution

---

# 1. Project Goal

The goal of the project is:

> Continuously analyze live markets, generate explainable trade
> candidates, rank them by expected quality, execute approved trades
> under a disciplined risk framework, and continuously evaluate trading
> performance.

The architecture is designed to support this objective while remaining
modular, explainable, and extensible.

---

# 2. High-Level Architecture

Live Market
        │
        ▼
Knowledge Layer
        │
        ▼
Decision Layer
        │
        ▼
Execution Layer
        │
        ▼
Performance Layer

Each layer has one primary responsibility.

---

# 3. Knowledge Layer

Purpose

Transform raw market observations into objective semantic knowledge.

Components

- ObservationHistory
- Semantic Construction Pipeline
- CanonicalMarketModel
- Ontology

Output

CanonicalMarketModel

The Knowledge Layer never generates trading decisions.

---

# 4. Decision Layer

Purpose

Interpret semantic knowledge and identify trading opportunities.

Components

- Market Interpretation
- Strategy
- Trade Candidate Generation
- Trade Candidate Evaluation
- Opportunity Ranking
- Risk Evaluation

Output

ExecutionDecision

The Decision Layer never communicates with brokers.

---

# 5. Execution Layer

Purpose

Convert approved trading decisions into broker actions.

Components

- Order Management
- Broker Adapter
- Position Monitoring
- Trade Lifecycle Management

Output

Executed trades and position updates.

Execution never performs market analysis.

---

# 6. Performance Layer

Purpose

Measure trading performance and system quality.

Components

- Trade History
- Performance Analytics
- Risk Metrics
- Strategy Evaluation
- Execution Statistics

Output

Performance reports and system feedback.

Performance data supports future system improvements.

---

# 7. Repository Structure

```text
domain/

    market_observation/

    semantic_construction/

    ontology/

    interpretation/

    strategy/

    risk/

    execution/

    portfolio/

    performance/

services/

config/

docs/

tests/
```

Each module has a clearly defined responsibility.

---

# 8. Architectural Responsibilities

Knowledge Layer

Answers:

What objectively exists?

Decision Layer

Answers:

What should be done?

Execution Layer

Answers:

How should it be done?

Performance Layer

Answers:

How well did it perform?

Responsibilities must never overlap.

---

# 9. Dependency Flow

ObservationHistory

↓

Semantic Construction

↓

CanonicalMarketModel

↓

Market Interpretation

↓

Strategy

↓

Trade Candidate Evaluation

↓

Risk

↓

Execution

↓

Broker

↓

Performance

Reverse dependencies are prohibited.

---

# 10. Explainability

Every decision produced by the system should be explainable.

Examples:

Market Interpretation

Trade Candidate

Risk Decision

Execution Decision

Performance Report

No component should produce unexplained outputs.

---

# 11. Modularity

Each architectural layer should be independently replaceable.

Examples

Replace ICT with Wyckoff.

Replace one Risk Engine with another.

Replace one Broker Adapter with another.

Replace one Strategy with another.

Other layers remain unchanged.

---

# 12. Theory Independence

The project separates:

Objective market facts

↓

Theory-dependent interpretation

↓

Trading decisions

↓

Execution

Different market theories may coexist while sharing the same semantic
ontology.

---

# 13. Testing Philosophy

Every architectural component should be testable in isolation.

Examples

Ontology tests

Interpretation tests

Strategy tests

Risk tests

Execution tests

Integration tests

Regression tests

Testing is a first-class architectural concern.

---

# 14. Future Extensions

The architecture supports future additions such as:

- multiple market theories
- portfolio optimization
- AI-assisted interpretation
- adaptive risk management
- reinforcement learning
- execution optimization
- distributed execution

Extensions must preserve architectural boundaries.

---

# 15. Theory 1.0 Architecture Freeze

Theory 1.0 freezes the following architecture:

Knowledge Layer

↓

Decision Layer

↓

Execution Layer

↓

Performance Layer

Future development should extend these layers rather than introducing
new architectural responsibilities.

---

# 16. Guiding Principles

The project follows these principles:

- Objective market representation
- Immutable semantic knowledge
- Explainable decision making
- Modular architecture
- Separation of responsibilities
- Theory independence
- Test-driven development
- Performance-driven evolution

Every architectural decision should support the project's primary goal:

Continuously analyze live markets, generate explainable trade
candidates, rank them by expected quality, execute approved trades
under a disciplined risk framework, and continuously evaluate which
reasoning patterns improve trading performance.