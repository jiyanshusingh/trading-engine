# Theory 1.0 Ontology Freeze

## Purpose

This document freezes the semantic ontology of Theory 1.0.

It defines the architectural boundaries of the Canonical Market Model
and establishes the semantic constructs that objectively describe market
structure.

Future development should extend execution and strategy layers rather
than modifying the ontology.

---

# 1. Architectural Principle

The ontology answers one question:

> What objectively exists in the market?

The ontology never answers:

- What should be traded?
- When should a trade be entered?
- How much risk should be taken?
- Which strategy should be executed?

Those responsibilities belong to higher architectural layers.

---

# 2. Canonical Semantic Dependency Graph

ObservationHistory
        ↓
Swing
        ↓
StructureEvent
        ↓
ProtectedSwing
        ↓
Expansion
        ↓
OriginRegion
        ↓
FairValueGap
        ↓
OrderBlock

Every semantic construct depends only on previously established semantic
facts.

No semantic layer may bypass this dependency graph.

---

# 3. Theory 1.0 Ontology

The Theory 1.0 ontology consists of exactly the following semantic
constructs.

ObservationHistory

Represents immutable market observations.

---

Swing

Represents confirmed structural turning points.

---

StructureEvent

Represents confirmed structural events.

Examples:

- BOS
- CHOCH

---

ProtectedSwing

Represents swings that define structural protection.

---

Expansion

Represents confirmed structural movement.

---

OriginRegion

Represents the structural origin of an Expansion.

---

FairValueGap

Represents a confirmed market imbalance.

---

OrderBlock

Represents a confirmed institutional price region.

---

No additional ontology objects are part of Theory 1.0.

---

# 4. Canonical Market Model

CanonicalMarketModel is the single source of semantic truth.

Every semantic layer is aggregated into one immutable model.

Builders consume the CanonicalMarketModel.

Execution layers consume the CanonicalMarketModel.

No component may construct its own semantic representation outside the
pipeline.

---

# 5. Construction Lifecycle

Every semantic construct follows exactly one lifecycle.

Ontology
        ↓
Candidate
        ↓
Candidate Detector
        ↓
Confirmation Result
        ↓
Confirmation Policy
        ↓
Builder
        ↓
Semantic Construction Pipeline
        ↓
CanonicalMarketModel

Alternative construction patterns are prohibited within Theory 1.0.

---

# 6. Immutability

Every ontology object is immutable.

Every Candidate is immutable.

Every Confirmation Result is immutable.

CanonicalMarketModel is immutable.

Intermediate semantic models are immutable.

Mutation of semantic facts is prohibited.

---

# 7. Separation of Responsibilities

Ontology

Represents semantic facts.

Candidate

Represents possible semantic facts.

Candidate Detector

Discovers candidates.

Confirmation Policy

Applies theory-specific rules.

Builder

Constructs immutable ontology objects.

Semantic Construction Pipeline

Coordinates construction.

CanonicalMarketModel

Aggregates semantic knowledge.

Execution Layer

Consumes semantic knowledge.

Strategy Layer

Consumes execution decisions.

---

# 8. Theory Separation

Objective market facts belong to the ontology.

Theory-specific interpretation belongs exclusively inside policies.

Future Theory versions may replace policies without modifying ontology
objects.

---

# 9. Dependency Rules

Higher semantic layers consume lower semantic layers.

Lower semantic layers never reference higher semantic layers.

Execution layers consume ontology.

Strategy layers consume execution.

Dependency direction is strictly one-way.

---

# 10. Region Semantics

Theory 1.0 contains three semantic regions.

OriginRegion

Represents structural origin.

FairValueGap

Represents market imbalance.

OrderBlock

Represents institutional price region.

Although these share geometric properties, they represent different
semantic concepts.

Inheritance between these ontology objects is intentionally avoided.

---

# 11. Stable References

Semantic objects reference one another using stable identifiers.

Examples:

- swing_index
- source_expansion_index
- source_origin_region_index
- source_fair_value_gap_index

Ontology objects do not embed references to other ontology objects.

---

# 12. Canonical Testing Requirements

Every semantic construct must include:

Ontology Tests

Candidate Tests

Candidate Detector Tests

Confirmation Tests

Builder Tests

Pipeline Tests

Regression Tests

No semantic construct is considered complete without passing the full
testing lifecycle.

---

# 13. Extension Policy

Theory 1.0 permits:

- new execution engines
- new strategy layers
- new liquidity models
- new risk models
- new portfolio models
- new Theory implementations

Theory 1.0 does not permit introducing additional ontology constructs
without explicit architectural review.

---

# 14. Architectural Boundary

The ontology ends with OrderBlock.

Everything beyond OrderBlock belongs to execution, interpretation, or
strategy.

The ontology describes the market.

It never decides what to trade.

---

# 15. Future Architecture

Execution Layer

Consumes CanonicalMarketModel.

Produces execution context.

↓

Market Bias

Liquidity

Execution Engine

↓

Strategy Layer

Produces trade decisions.

↓

Risk Layer

Determines position sizing and exposure.

↓

Portfolio Layer

Coordinates multiple strategies and instruments.

---

# 16. Theory 1.0 Completion

Theory 1.0 freezes:

✓ Semantic Dependency Graph

✓ Immutable Ontology

✓ Candidate Pattern

✓ Confirmation Pattern

✓ Builder Pattern

✓ Semantic Construction Pipeline

✓ CanonicalMarketModel

✓ Theory Separation

✓ Testing Lifecycle

Future development should focus on execution, strategy, and portfolio
management while preserving these architectural foundations.

---

# 17. Final Principle

The ontology exists to describe the market objectively.

Execution exists to interpret the ontology.

Strategy exists to act on execution.

Keeping these responsibilities separate preserves clarity,
testability, extensibility, and long-term architectural stability.

This document marks the completion of the Theory 1.0 semantic ontology.