# Legacy Order Block Analysis

## Purpose

This document analyzes the legacy Order Block implementation and
defines its migration into the Theory 1.0 Semantic Construction
Architecture.

The objective is to identify:

- objective market facts
- semantic responsibilities
- theory-specific rules
- dependencies

before implementing the new ontology.

---

# 1. What is an Order Block?

An Order Block is an immutable semantic representation of an
institutional accumulation or distribution region.

It is a higher-order semantic construct.

An Order Block is not:

- a candle
- a Swing
- a Structure Event
- a Protected Swing
- an Expansion
- an Origin Region
- a Fair Value Gap

It is a semantic representation derived from previously established
market structure and imbalance.

---

# 2. Structural Definition

An Order Block represents the institutional price region associated
with a completed structural sequence.

Once confirmed it becomes an immutable semantic construct.

---

# 3. Inputs

The legacy implementation derives Order Blocks from:

- ObservationHistory
- Confirmed Expansions
- Confirmed Origin Regions
- Confirmed Fair Value Gaps

ObservationHistory provides objective market observations.

Previously established semantic layers provide structural context.

---

# 4. Outputs

Each Order Block defines:

- Upper Price
- Lower Price
- Direction
- Start Timestamp
- End Timestamp

These outputs become inputs for execution and strategy layers.

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
        ↓
Order Blocks

Order Blocks consume semantic knowledge rather than rediscovering
market structure.

---

# 6. Consumers

Order Blocks are consumed by:

- Execution Engine
- Trade Entry Models
- Liquidity Models
- Risk Management
- Strategy Layer

---

# 7. Legacy Responsibilities

The legacy implementation currently mixes:

- discovery
- validation
- DataFrame mutation
- institutional logic
- state management

These responsibilities will be separated in Theory 1.0.

---

# 8. New Semantic Architecture

OrderBlockCandidateDetector
            ↓
OrderBlockCandidate
            ↓
OrderBlockConfirmationPolicy
            ↓
OrderBlockBuilder
            ↓
OrderBlock

---

# 9. Ontology

OrderBlock is an immutable Value Object.

It performs no computation.

It represents an established institutional price region.

---

# 10. Candidate

An OrderBlockCandidate represents a possible Order Block before
confirmation.

Candidates are discovered from objective observations together with
existing semantic knowledge.

Candidates are not authoritative.

---

# 11. Confirmation

The confirmation policy determines whether an
OrderBlockCandidate becomes an OrderBlock.

Theory-specific rules belong exclusively inside the confirmation policy.

---

# 12. Builder

The OrderBlockBuilder:

- requests candidates
- applies confirmation
- constructs immutable OrderBlock objects

The builder performs no market analysis.

---

# 13. Pipeline Position

Order Blocks are constructed after:

- Swings
- Structure Events
- Protected Swings
- Expansions
- Origin Regions
- Fair Value Gaps

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
        ↓
Order Blocks

---

# 14. Theory Separation

Objective facts:

- Upper Boundary
- Lower Boundary
- Direction
- Start Timestamp
- End Timestamp

Theory-specific rules:

- Order Block qualification
- Institutional filtering
- Mitigation rules
- Validation
- Replacement
- Invalidation

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
        ↓
Order Blocks

Order Blocks must never bypass lower semantic layers.

---

# 17. Future Semantic Consumers

Order Blocks provide institutional semantic knowledge for:

- Execution Engine
- Market Bias Engine
- Entry Models
- Risk Models
- Trade Management
- Portfolio Construction

Future execution components should consume Order Blocks rather than
rediscovering institutional regions independently.

---

# 18. Theory 1.0 Freeze

Theory 1.0 freezes only the architectural responsibilities of the
Order Block layer.

Future Theory versions may modify qualification and confirmation rules
while preserving:

- immutable ontology
- builder pattern
- semantic dependency graph
- Canonical Market Model

---

# 19. Theory 1.0 Completion

Order Block is the final semantic ontology layer of Theory 1.0.

Completion of this migration freezes the Theory 1.0 semantic ontology.

Future development should focus on:

- Execution Engine
- Liquidity Models
- Market Bias
- Entry Models
- Risk Management
- Strategy Layer

rather than introducing additional semantic ontology layers.