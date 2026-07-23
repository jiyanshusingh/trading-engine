# Semantic Construction Conventions

## Purpose

This document defines the architectural conventions governing the
Semantic Construction Pipeline.

These conventions are frozen for Theory 1.0 and apply to every semantic
construct within the Canonical Market Model.

The objective is consistency, determinism, and separation of concerns.

---

# 1. Semantic Dependency Principle

Every semantic construct depends only on previously established semantic
facts.

Semantic layers must never bypass lower layers.

Canonical dependency graph:

ObservationHistory
        ↓
Swings
        ↓
Structure Events
        ↓
Protected Swings
        ↓
Expansions
        ↓
Origin Regions
        ↓
Fair Value Gaps
        ↓
Order Blocks

---

# 2. Canonical Market Model Principle

The CanonicalMarketModel is the single source of semantic truth.

Semantic builders consume the CanonicalMarketModel.

Builders must never consume arbitrary collections of semantic objects.

Correct:

builder.build(model)

Incorrect:

builder.build(
    swings,
    events,
    regions,
)

---

# 3. Immutable Ontology Principle

Every ontology object is immutable.

Ontology objects represent semantic facts.

Ontology objects perform no computation.

They never:

- detect
- validate
- calculate
- mutate
- confirm

---

# 4. Candidate Principle

Every ontology object has a corresponding Candidate.

Candidate objects represent possible semantic facts.

Candidates are not authoritative.

Candidates are immutable.

---

# 5. Candidate Detector Principle

Candidate Detectors discover Candidates.

Candidate Detectors may analyze:

- ObservationHistory
- CanonicalMarketModel

depending on semantic dependencies.

Candidate Detectors never:

- mutate the model
- confirm candidates
- construct ontology objects

---

# 6. Confirmation Principle

Confirmation Policies determine whether a Candidate becomes a semantic
fact.

All Theory-specific logic belongs exclusively inside Confirmation
Policies.

Confirmation Policies never:

- construct ontology objects
- modify the CanonicalMarketModel

---

# 7. Builder Principle

Builders construct immutable ontology objects.

Builders perform no market analysis.

Builders perform no theory-specific reasoning.

Builders:

- request Candidates
- invoke Confirmation Policies
- construct immutable objects

Nothing more.

---

# 8. Pipeline Principle

The Semantic Construction Pipeline builds semantic knowledge one layer at
a time.

Each stage consumes the semantic model produced by previous stages.

Builders must never bypass the dependency graph.

---

# 9. Observation Principle

ObservationHistory is immutable.

ObservationHistory represents objective market observations.

ObservationHistory is never modified by semantic construction.

---

# 10. Theory Separation Principle

Objective facts belong to ontology.

Theory belongs to policies.

Future Theory versions may replace policies without changing ontology.

---

# 11. Single Responsibility Principle

Every component has exactly one responsibility.

Ontology
    represents facts.

Candidate
    represents possible facts.

Detector
    discovers candidates.

Confirmation Policy
    validates candidates.

Builder
    constructs ontology objects.

Pipeline
    orchestrates construction.

CanonicalMarketModel
    aggregates semantic knowledge.

---

# 12. Identifier Principle

Semantic objects reference other semantic objects by stable identifiers.

Examples:

- swing_index
- confirmation_event_index
- source_expansion_index

Ontology objects should avoid embedding references to other ontology
objects.

---

# 13. Region Principle

Price regions are represented explicitly.

Region-based ontology includes:

- OriginRegion
- FairValueGap
- OrderBlock

Every region should define:

- upper_price
- lower_price
- direction
- start_timestamp
- end_timestamp

Regions represent bounded price areas rather than single prices.

---

# 14. Testing Principle

Every semantic construct follows the same testing lifecycle.

Ontology
↓

Ontology Tests
↓

Candidate
↓

Candidate Tests
↓

Candidate Detector
↓

Detector Tests
↓

Confirmation Result
↓

Confirmation Tests
↓

Builder
↓

Builder Tests
↓

Pipeline Tests
↓

Regression Tests

No stage is skipped.

---

# 15. Migration Principle

Legacy implementations are migrated in the following order:

1. Legacy Analysis
2. Immutable Ontology
3. Candidate
4. Candidate Detector
5. Confirmation Result
6. Confirmation Policy
7. Builder
8. Pipeline Integration
9. Regression Validation

Architecture is frozen before implementation begins.

---

# 16. Immutability Principle

Every semantic layer produces immutable objects.

Intermediate CanonicalMarketModel instances are immutable.

Builders never mutate existing semantic layers.

---

# 17. Extensibility Principle

Future semantic constructs must follow the same architectural lifecycle.

New semantic constructs must not introduce alternative construction
patterns.

Consistency is preferred over optimization.

---

# 18. Theory 1.0 Freeze

Theory 1.0 freezes:

- Semantic Dependency Graph
- Candidate Pattern
- Confirmation Pattern
- Builder Pattern
- Immutable Ontology
- Canonical Market Model
- Semantic Construction Pipeline

Future Theory versions may evolve semantic rules while preserving these
architectural conventions.