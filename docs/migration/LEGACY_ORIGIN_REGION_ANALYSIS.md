# Legacy Origin Region Analysis

## Purpose

This document analyzes the legacy Origin Region implementation and
defines its migration into the Theory 1.0 Semantic Construction
Architecture.

The objective is to identify:

- objective market facts
- semantic responsibilities
- theory-specific rules
- dependencies

before implementing the new ontology.

---

# 1. What is an Origin Region?

An Origin Region is the structural price region from which a confirmed
Expansion originated.

It represents the institutional origin of a completed structural move.

An Origin Region is not:

- a candle
- a Swing
- a Structure Event
- an Expansion

It is a semantic region derived from completed market structure.

---

# 2. Structural Definition

An Origin Region identifies the price area responsible for initiating a
confirmed Expansion.

Once established, it becomes an immutable semantic construct.

---

# 3. Inputs

The legacy implementation derives Origin Regions from:

- Confirmed Expansions
- Protected Swings
- Confirmed Structure Events

Origin Regions never inspect raw market observations directly.

---

# 4. Outputs

Each Origin Region defines:

- Start Timestamp
- End Timestamp
- Upper Price
- Lower Price
- Direction
- Source Expansion

These outputs become inputs for higher semantic layers.

---

# 5. Dependencies

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

Origin Regions depend only on previously established semantic facts.

---

# 6. Consumers

Origin Regions are consumed by:

- Fair Value Gap detection
- Order Block construction
- Execution models
- Liquidity analysis

---

# 7. Legacy Responsibilities

The legacy implementation currently mixes:

- discovery
- validation
- DataFrame mutation
- structural calculations
- state management

These responsibilities will be separated in Theory 1.0.

---

# 8. New Semantic Architecture

OriginRegionCandidateDetector
            ↓
OriginRegionCandidate
            ↓
OriginRegionConfirmationPolicy
            ↓
OriginRegionBuilder
            ↓
OriginRegion

---

# 9. Ontology

OriginRegion is an immutable Value Object.

It performs no computation.

It represents an established structural fact.

---

# 10. Candidate

An OriginRegionCandidate represents a potential Origin Region before
confirmation.

Candidates are discovered from existing semantic constructs.

Candidates are not authoritative.

---

# 11. Confirmation

The confirmation policy determines whether an
OriginRegionCandidate becomes an OriginRegion.

Theory-specific rules belong exclusively inside the confirmation policy.

---

# 12. Builder

The OriginRegionBuilder:

- requests candidates
- applies confirmation
- constructs immutable OriginRegion objects

The builder performs no market analysis.

---

# 13. Pipeline Position

Origin Regions are constructed after:

- Swings
- Structure Events
- Protected Swings
- Expansions

Pipeline order:

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

---

# 14. Theory Separation

Objective facts:

- Source Expansion
- Start Timestamp
- End Timestamp
- Upper Boundary
- Lower Boundary
- Direction

Theory-specific rules:

- Origin qualification
- Region selection
- Boundary determination
- Filtering
- Replacement

Theory-specific behavior belongs exclusively inside policies.

---

# 15. Migration Strategy

Step 1

Analyze legacy implementation.

Step 2

Identify objective semantic facts.

Step 3

Separate Theory rules.

Step 4

Create immutable ontology.

Step 5

Create candidate.

Step 6

Create candidate detector.

Step 7

Create confirmation result.

Step 8

Create confirmation policy.

Step 9

Create builder.

Step 10

Integrate into SemanticConstructionPipeline.

Step 11

Regression against legacy engine.

---

# 16. Canonical Dependency Graph

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

Origin Regions must never bypass lower semantic layers.

---

# 17. Future Semantic Consumers

Origin Regions provide the structural foundation for:

- Fair Value Gaps
- Order Blocks
- Institutional execution models

Future semantic constructs should consume Origin Regions rather than
rediscovering structural origins from lower-level semantic objects.

---

# 18. Theory 1.0 Freeze

Theory 1.0 freezes only the architectural responsibilities of the
Origin Region layer.

Future Theory versions may modify qualification and confirmation rules
while preserving:

- immutable ontology
- builder pattern
- semantic dependency graph
- Canonical Market Model