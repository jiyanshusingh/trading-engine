# Semantic Dependency Graph

## Purpose

This document defines the canonical dependency graph for the Semantic
Construction Pipeline.

It specifies the order in which semantic constructs are derived from one
another.

The dependency graph is independent of Theory versions.

Theory changes may alter the rules used to construct a semantic object,
but they must not violate the dependency graph.

---

# Core Principle

Every semantic construct is built only from semantic facts that already
exist.

A construct must never rediscover lower-level semantics directly from
raw market observations.

This guarantees:

- deterministic construction
- single source of truth
- separation of responsibilities
- theory independence
- composability

---

# Layer 0 — Observation Domain

Source of Truth

ObservationHistory

Contains:

- Market Observations
- Metadata
- Timeframe
- Symbol

Produces no semantic interpretation.

---

# Layer 1 — Primary Semantic Constructs

Input

ObservationHistory

Produces

- Swings

Purpose

Identify objective turning points in price.

No higher-level interpretation exists at this stage.

---

# Layer 2 — Secondary Semantic Constructs

Input

- Swings

Produces

- Structure Events

Examples

- BOS
- CHOCH

Purpose

Interpret structural relationships between confirmed swings.

Structure Events never inspect raw candles directly.

---

# Layer 3 — Tertiary Semantic Constructs

Input

- Swings
- Structure Events

Produces

- Protected Swings

Purpose

Determine which confirmed Swing is currently protected by market
structure.

Protection is derived from confirmed structural events.

---

# Layer 4 — Expansion Layer

Input

- Protected Swings
- Structure Events

Produces

- Expansions

Purpose

Represent completed structural movements.

Expansions are built only after market structure has been established.

---

# Layer 5 — Origin Layer

Input

- Expansions

Produces

- Origin Regions

Purpose

Locate the structural origin of completed expansions.

---

# Layer 6 — Imbalance Layer

Input

- Expansions
- Origin Regions

Produces

- Fair Value Gaps

Purpose

Represent delivery imbalances within established structure.

---

# Layer 7 — Institutional Representation Layer

Input

- Fair Value Gaps
- Origin Regions
- Protected Swings

Produces

- Order Blocks

Purpose

Represent institutional price regions according to Theory.

---

# Canonical Dependency Graph

ObservationHistory
        │
        ▼
Swings
        │
        ▼
Structure Events
        │
        ▼
Protected Swings
        │
        ▼
Expansions
        │
        ▼
Origin Regions
        │
        ▼
Fair Value Gaps
        │
        ▼
Order Blocks

---

# Dependency Rules

Rule 1

Higher layers may depend only on lower layers.

Never the reverse.

---

Rule 2

No semantic construct may bypass an intermediate layer.

Incorrect:

ObservationHistory
        │
        ▼
Order Block

Correct:

ObservationHistory
        ▼
Swings
        ▼
Structure Events
        ▼
Protected Swings
        ▼
Expansions
        ▼
Origin Regions
        ▼
Fair Value Gaps
        ▼
Order Blocks

---

Rule 3

Builders never mutate existing semantic constructs.

Each builder creates new immutable objects.

---

Rule 4

Semantic constructs never perform computation.

They represent established facts only.

---

Rule 5

Theory-specific rules belong only inside policies.

Ontology objects remain theory independent.

---

Rule 6

Builders consume semantic facts rather than rediscovering them.

Example

SwingBuilder

Input

ObservationHistory

Output

Swings

StructureEventBuilder

Input

Swings

Output

Structure Events

ProtectedSwingBuilder

Input

Swings
Structure Events

Output

Protected Swings

---

# Semantic Construction Pipeline

The SemanticConstructionPipeline progressively enriches the
CanonicalMarketModel.

Stage 1

ObservationHistory

↓

Swings

↓

CanonicalMarketModel

Stage 2

CanonicalMarketModel

↓

Structure Events

↓

CanonicalMarketModel

Stage 3

CanonicalMarketModel

↓

Protected Swings

↓

CanonicalMarketModel

Stage 4

CanonicalMarketModel

↓

Expansions

↓

CanonicalMarketModel

Stage 5

CanonicalMarketModel

↓

Origin Regions

↓

CanonicalMarketModel

Stage 6

CanonicalMarketModel

↓

Fair Value Gaps

↓

CanonicalMarketModel

Stage 7

CanonicalMarketModel

↓

Order Blocks

↓

Completed CanonicalMarketModel

---

# Architectural Benefits

This dependency graph provides:

- Single source of truth
- Deterministic construction
- Immutable semantic layers
- Separation of concerns
- Theory independence
- Extensibility
- Easier testing
- Regression-safe migration
- Institutional-grade architecture

---

# Theory 1.0 Freeze

This dependency graph is frozen for Theory 1.0.

Future Theory versions may introduce additional semantic constructs or
modify confirmation policies, but they must preserve the dependency
direction defined in this document unless an explicit architectural
revision is approved.