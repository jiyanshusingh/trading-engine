# Legacy Structure Event Engine Analysis

Version 1.0

---

# Purpose

This document analyzes the responsibilities of the legacy
Structure Event Engine.

Its purpose is not to preserve implementation details.

Its purpose is to identify the semantic responsibilities that
must be migrated into the new semantic architecture.

---

# Legacy Engine

Current implementation

engines/structure_event_engine.py

---

# Purpose of the Engine

The Structure Event Engine transforms completed structural
analysis into immutable StructureEvent objects.

A StructureEvent represents a confirmed structural change
within the market.

Examples

- BOS
- CHOCH

---

# Inputs

The legacy engine consumes:

- Observation History
- Confirmed Swings
- Protected Swings
- BOS Validation
- CHOCH Validation
- Structural Direction
- Structure Levels
- Displacement Measurements

---

# Outputs

The engine produces immutable StructureEvent objects.

Each StructureEvent contains:

- Event Type
- Direction
- Timestamp
- Candle Index
- Broken Swing
- Base Swing
- Structure Level
- Validity
- Supporting Evidence

---

# Legacy Responsibilities

---

## Responsibility 1

### Detect Structure Event Candidates

Description

Identify candles that qualify as potential
structure events.

Current implementation

Uses

- BOS_Valid
- CHOCH_Valid

New architecture

ICTStructureEventCandidateDetector

Status

❌ Not Migrated

---

## Responsibility 2

### Determine Event Semantics

Description

Determine:

- Event Type
- Direction
- Base Swing
- Broken Swing
- Structure Level

Current implementation

Conditional logic inside the engine.

New architecture

ICTStructureEventConfirmationPolicy

Status

❌ Not Migrated

---

## Responsibility 3

### Construct StructureEvent

Description

Create immutable StructureEvent objects.

Current implementation

create_event()

New architecture

StructureEventBuilder

Status

❌ Not Migrated

---

# Legacy DataFrame Dependencies

The current implementation depends on the following
DataFrame columns.

BOS

- BOS_Valid
- Bullish_BOS
- BOS_Level
- BOS_Broken_Swing_Index
- BOS_Displacement

Protected Swings

- Protected_Low_Index
- Protected_High_Index

CHOCH

- CHOCH_Valid
- Bullish_CHOCH
- CHOCH_Level
- CHOCH_Base_Swing_Index
- CHOCH_Broken_Swing_Index
- CHOCH_Displacement

These columns represent implementation details.

They shall not exist within the ontology.

---

# New Semantic Architecture

The Structure Event lifecycle becomes

Observation History

↓

Confirmed Swings

↓

Structure Event Candidate Detector

↓

Structure Event Candidates

↓

Structure Event Confirmation Policy

↓

Confirmed Structure Events

↓

Structure Event Builder

↓

Canonical Market Model

---

# Migration Status

| Responsibility | New Component | Status |
|----------------|--------------|--------|
| Candidate Detection | ICTStructureEventCandidateDetector | ❌ Pending |
| Confirmation | ICTStructureEventConfirmationPolicy | ❌ Pending |
| Construction | StructureEventBuilder | ❌ Pending |
| Pipeline Integration | SemanticConstructionPipeline | ❌ Pending |
| Regression | Structure Event Regression | ❌ Pending |

---

# Improvements Over Legacy Design

The legacy engine stores additional information in an
untyped metadata dictionary.

Example

metadata["displacement"]

The new architecture shall replace untyped metadata with
explicit domain fields or dedicated immutable value objects.

This improves

- Type safety
- Readability
- Testability
- Semantic clarity

---

# Completion Criteria

The Structure Event migration is complete when

- Candidate detection reproduces legacy behaviour.
- Confirmation reproduces legacy behaviour.
- Immutable StructureEvent objects are constructed.
- Pipeline integration is complete.
- Regression against the legacy engine passes.
- StructureEvent v1.0 is frozen.

---

# Engineering Workflow

The Structure Event migration follows the established
semantic migration process.

Theory

↓

Specification

↓

Value Object

↓

Candidate

↓

Candidate Detector

↓

Confirmation Policy

↓

Builder

↓

Pipeline

↓

Regression

↓

Freeze