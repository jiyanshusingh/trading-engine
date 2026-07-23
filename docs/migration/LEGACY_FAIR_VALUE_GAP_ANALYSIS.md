# Legacy Fair Value Gap Analysis

## Purpose

This document analyzes the legacy Fair Value Gap implementation and
defines its migration into the Theory 1.0 Semantic Construction
Architecture.

The objective is to identify:

- objective market facts
- semantic responsibilities
- theory-specific rules
- dependencies

before implementing the new ontology.

---

# 1. What is a Fair Value Gap?

A Fair Value Gap is an imbalance in price created when market movement
leaves a region with little or no opposing trading activity.

It represents a semantic price imbalance.

A Fair Value Gap is not:

- a candle
- a Swing
- a Structure Event
- an Expansion
- an Origin Region

It is an immutable semantic representation of a confirmed price
imbalance.

---

# 2. Structural Definition

A Fair Value Gap is identified from market observations after sufficient
structural context has been established.

The gap is represented by:

- upper boundary
- lower boundary
- start timestamp
- end timestamp
- direction

Once confirmed it becomes an immutable semantic construct.

---

# 3. Inputs

The legacy implementation derives Fair Value Gaps from:

- ObservationHistory
- Confirmed Origin Regions
- Confirmed Expansions
- Confirmed Structure Events

ObservationHistory provides the objective price data.

Previously established semantic layers provide structural context.

---

# 4. Outputs

Each Fair Value Gap defines:

- Upper Price
- Lower Price
- Direction
- Start Timestamp
- End Timestamp

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
        ↓
Origin Regions
        ↓
Fair Value Gaps

The detector may inspect ObservationHistory while consuming the
CanonicalMarketModel.

---

# 6. Consumers

Fair Value Gaps are consumed by:

- Order Block construction
- Execution models
- Liquidity analysis
- Trade management

---

# 7. Legacy Responsibilities

The legacy implementation currently mixes:

- discovery
- validation
- DataFrame mutation
- imbalance calculations
- state management

These responsibilities will be separated in Theory 1.0.

---

# 8. New Semantic Architecture

FairValueGapCandidateDetector
            ↓
FairValueGapCandidate
            ↓
FairValueGapConfirmationPolicy
            ↓
FairValueGapBuilder
            ↓
FairValueGap

---

# 9. Ontology

FairValueGap is an immutable Value Object.

It performs no computation.

It represents an established semantic imbalance.

---

# 10. Candidate

A FairValueGapCandidate represents a possible Fair Value Gap before
confirmation.

Candidates are discovered from objective observations together with
existing semantic knowledge.

Candidates are not authoritative.

---

# 11. Confirmation

The confirmation policy determines whether a
FairValueGapCandidate becomes a FairValueGap.

Theory-specific rules belong exclusively inside the confirmation policy.

---

# 12. Builder

The FairValueGapBuilder:

- requests candidates
- applies confirmation
- constructs immutable FairValueGap objects

The builder performs no market analysis.

---

# 13. Pipeline Position

Fair Value Gaps are constructed after:

- Swings
- Structure Events
- Protected Swings
- Expansions
- Origin Regions

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
        ↓
Fair Value Gaps

---

# 14. Theory Separation

Objective facts:

- Upper Boundary
- Lower Boundary
- Direction
- Start Timestamp
- End Timestamp

Theory-specific rules:

- Gap qualification
- Minimum imbalance
- Filtering
- Mitigation rules
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
        ↓
Fair Value Gaps

Fair Value Gaps must never bypass lower semantic layers for structural
interpretation.

---

# 17. Future Semantic Consumers

Fair Value Gaps provide semantic imbalance information for:

- Order Blocks
- Institutional execution models
- Trade planning

Future semantic constructs should consume Fair Value Gaps rather than
rediscovering imbalance independently.

---

# 18. Theory 1.0 Freeze

Theory 1.0 freezes only the architectural responsibilities of the Fair
Value Gap layer.

Future Theory versions may modify qualification and confirmation rules
while preserving:

- immutable ontology
- builder pattern
- semantic dependency graph
- Canonical Market Model