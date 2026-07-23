# Legacy Swing Engine Analysis

## Purpose

This document analyzes the responsibilities of the legacy Swing Engine.

Its purpose is **not** to preserve implementation details.

Its purpose is to identify the semantic responsibilities that must be
migrated into the new semantic architecture.

---

# Legacy Engine

Current implementation:

engines/swing_engine.py

---

# Inputs

The legacy engine consumes:

- Observation History (OHLCV)
- ATR values
- Swing Lookback
- Minimum Swing ATR Threshold

---

# Outputs

The engine produces:

- Swing High
- Swing Low
- Swing Strength

These outputs are currently represented as DataFrame columns.

In the new architecture they become immutable ontology objects.

---

# Responsibility Analysis

## Responsibility 1

### Detect Swing Candidates

Description

Detect local extrema using the configured lookback window.

Current implementation

Comparison against neighboring highs/lows.

New architecture

ICTSwingCandidateDetector

Status

✅ Migrated

---

## Responsibility 2

### Confirm Swing

Description

Determine whether a SwingCandidate becomes a confirmed Swing.

Current implementation

Uses future observations.

New architecture

ICTSwingConfirmationPolicy

Status

🟡 Partially Migrated

Completed

- Confirmation window
- Confirmation index

Remaining

- ATR displacement
- ICT confirmation rules

---

## Responsibility 3

### Calculate Swing Strength

Description

Measure the strength of a confirmed swing.

Current implementation

ATR displacement.

New architecture

SwingStrengthCalculator

Status

❌ Not Migrated

---

## Responsibility 4

### Construct Swing

Description

Create immutable semantic Swing objects.

Current implementation

Implicit DataFrame mutation.

New architecture

SwingBuilder

Status

✅ Migrated

---

# Legacy DataFrame Responsibilities

Current engine mutates:

- Swing_High
- Swing_Low
- Swing_Strength

The new architecture does not mutate observations.

Instead it produces immutable ontology objects.

---

# Migration Status

| Responsibility | New Component | Status |
|----------------|--------------|--------|
| Candidate Detection | ICTSwingCandidateDetector | ✅ Complete |
| Confirmation | ICTSwingConfirmationPolicy | 🟡 Partial |
| Strength | SwingStrengthCalculator | ❌ Pending |
| Swing Construction | SwingBuilder | ✅ Complete |

---

# Remaining Work

1. Implement SwingStrengthCalculator.
2. Migrate ATR displacement.
3. Update ICTSwingConfirmationPolicy.
4. Perform regression against the legacy engine.
5. Freeze Swing v1.0.

---

# Completion Criteria

Swing migration is complete when:

- Candidate detection matches legacy behavior.
- Confirmation matches legacy behavior.
- Strength calculation matches legacy behavior.
- Regression tests pass.
- SwingBuilder produces identical semantic results.