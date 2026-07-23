# Legacy Expansion Analysis

## Purpose

This document analyzes the legacy Expansion implementation and defines
its migration into the Theory 1.0 Semantic Construction Architecture.

The objective is to identify:

- objective market facts
- semantic responsibilities
- theory-specific rules
- dependencies

before implementing the new ontology.

---

# 1. What is an Expansion?

An Expansion is a completed structural movement anchored at a Base Swing
and confirmed by a valid Structure Event.

An Expansion represents a structural leg of the market.

It is not:

- a candle
- a Swing
- a BOS
- a CHOCH

It is the completed movement between structural events.

---

# 2. Structural Definition

An Expansion begins at a Base Swing.

An Expansion ends when a valid Structure Event confirms that the market
has completed the structural movement.

The Expansion is therefore an immutable semantic construct describing
that completed movement.

---

# 3. Inputs

The legacy implementation derives Expansions from:

- Confirmed Swings
- Confirmed Structure Events
- Protected Swings

The Expansion layer never analyzes raw market observations directly.

---

# 4. Outputs

Each Expansion defines:

- Base Swing
- Confirmation Structure Event
- Direction
- Start Time
- End Time
- Start Price
- End Price

Future semantic constructs consume these outputs.

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

An Expansion depends on previously established semantic facts.

---

# 6. Consumers

Expansions are consumed by:

- Origin Region detection
- Fair Value Gap analysis
- Order Block construction
- Trend interpretation
- Execution models

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

ExpansionCandidateDetector
            ↓
ExpansionCandidate
            ↓
ExpansionConfirmationPolicy
            ↓
ExpansionBuilder
            ↓
Expansion

---

# 9. Ontology

Expansion is an immutable Value Object.

It performs no computation.

It represents an established structural fact.

---

# 10. Candidate

An ExpansionCandidate represents a potential completed Expansion before
confirmation.

Candidates are discovered from existing semantic constructs.

Candidates are not authoritative.

---

# 11. Confirmation

The confirmation policy determines whether an ExpansionCandidate becomes
an Expansion.

Theory-specific rules belong exclusively inside the confirmation policy.

---

# 12. Builder

The ExpansionBuilder:

- requests candidates
- applies confirmation
- constructs immutable Expansion objects

The builder performs no market analysis.

---

# 13. Pipeline Position

Expansion is constructed after:

- Swings
- Structure Events
- Protected Swings

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

---

# 14. Theory Separation

Objective facts:

- Base Swing
- Confirmation Event
- Start Timestamp
- End Timestamp
- Direction

Theory-specific rules:

- Expansion qualification
- Confirmation rules
- Filtering
- Replacement
- Structural interpretation

Theory-specific behavior belongs inside policies.

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

An Expansion must never bypass lower semantic layers.

---

# 17. Theory 1.0 Freeze

Theory 1.0 freezes only the architectural responsibilities of the
Expansion layer.

Future Theory versions may modify confirmation rules while preserving:

- immutable ontology
- builder pattern
- semantic dependency graph
- Canonical Market Model