# Legacy Protected Swing Analysis

## Purpose

This document analyzes the legacy Protected Swing implementation and
defines its migration into the Theory 1.0 Semantic Construction
Architecture.

The goal is to identify:

- objective market facts
- theory-specific rules
- dependencies
- semantic responsibilities

before writing any new code.

---

# 1. What is a Protected Swing?

A Protected Swing is a previously confirmed Swing that becomes the
structural reference for future market structure.

It represents the swing currently protected by institutional order flow.

A Protected Swing is not a Swing.

It is a semantic construct derived from one or more Structure Events.

---

# 2. Inputs

The legacy implementation derives Protected Swings from:

- Confirmed Swings
- Confirmed BOS
- Confirmed CHOCH

It does not operate directly on raw candles.

---

# 3. Outputs

The legacy engine produces:

- Protected High
- Protected Low

These become the structural reference for future BOS and CHOCH detection.

---

# 4. Dependencies

Protected Swing depends on:

ObservationHistory
        ↓
Confirmed Swing
        ↓
Confirmed Structure Event
        ↓
Protected Swing

---

# 5. Used By

Protected Swings are consumed by:

- BOS Detection
- CHOCH Detection
- Expansion Construction
- Trend Interpretation

---

# 6. Theory Separation

Objective facts:

- Which confirmed Swing becomes protected
- Which Structure Event caused protection
- When protection occurred

Theory-specific decisions:

- ICT protection rules
- Replacement rules
- Invalidation rules
- Directional interpretation

Theory rules must remain inside the confirmation policy.

---

# 7. Legacy Responsibilities

The legacy implementation currently mixes:

- discovery
- confirmation
- state mutation
- DataFrame updates

These responsibilities will be separated.

---

# 8. New Semantic Architecture

ProtectedSwingCandidateDetector
            ↓
ProtectedSwingCandidate
            ↓
ProtectedSwingConfirmationPolicy
            ↓
ProtectedSwingBuilder
            ↓
ProtectedSwing

---

# 9. Target Ontology

ProtectedSwing will become an immutable Value Object.

It will not perform computation.

It represents an established semantic fact.

---

# 10. Candidate

The candidate represents a potential Protected Swing discovered from
existing semantic constructs.

A candidate is not yet authoritative.

---

# 11. Confirmation

The confirmation policy decides whether a candidate becomes a real
Protected Swing according to Theory 1.0.

---

# 12. Builder

The builder:

- requests candidates
- applies confirmation policy
- constructs immutable ProtectedSwing objects

The builder performs no market analysis.

---

# 13. Canonical Model

The SemanticConstructionPipeline will populate:

CanonicalMarketModel.protected_swings

alongside:

- swings
- structure_events

---

# 14. Migration Strategy

Step 1

Study legacy implementation.

Step 2

Identify objective facts.

Step 3

Separate theory rules.

Step 4

Design immutable ontology.

Step 5

Create candidate.

Step 6

Create detector.

Step 7

Create confirmation policy.

Step 8

Create builder.

Step 9

Integrate into SemanticConstructionPipeline.

Step 10

Regression against legacy engine.

---

# 15. Theory 1.0 Freeze

Theory 1.0 defines only the architectural migration.

The semantic rules governing Protected Swings may evolve in future
Theory versions without changing the surrounding architecture.