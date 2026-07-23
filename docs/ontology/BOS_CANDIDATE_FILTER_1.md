# BOS Candidate Filter 1

## Status

**Experimental**

This document defines the first experimental filter for identifying
Break of Structure (BOS) candidates.

It is **not** part of the ontology.

It is **not** part of the BOS definition.

It represents a research hypothesis that must be validated against
historical market data before implementation.

---

# Objective

Reduce the universe of ordinary broken swings into a smaller set of
plausible BOS candidates using a deterministic and objective rule.

The filter should significantly reduce false candidates while avoiding
subjective interpretation.

---

# Motivation

Previous experiments established the following observations.

## Observation 1

Nearly every confirmed swing is eventually broken.

Therefore,

```
Broken Swing
≠
BOS
```

Breaking a swing alone cannot define Break of Structure.

---

## Observation 2

Broken swings naturally partition into two groups.

Latest confirmed swings.

Superseded swings.

These groups exhibit substantially different structural lifetimes.

This suggests that structural context may be useful for candidate
selection.

---

# Research Hypothesis

A break event is a BOS candidate only if it breaks the latest confirmed
swing of the same type.

For example,

Bullish

```
Latest Confirmed High

↓

Broken

↓

BOS Candidate
```

Bearish

```
Latest Confirmed Low

↓

Broken

↓

BOS Candidate
```

This hypothesis is intentionally simple.

Its purpose is to determine whether a single deterministic filter can
eliminate a significant proportion of ordinary broken swings.

---

# Input

Confirmed Swings

Broken Swing Events

No additional market structure objects are required.

---

# Output

Each broken swing is classified as

```
Candidate
```

or

```
Rejected
```

No StructureEvent objects are created.

No BOS objects are created.

The filter only produces candidate break events.

---

# Algorithm

For every broken swing,

Determine whether the broken swing is the latest confirmed swing of the
same type immediately before the break event.

If true,

```
Candidate
```

Else,

```
Reject
```

---

# Determinism

The filter must satisfy the following properties.

- Objective
- Deterministic
- Local
- Reproducible

Two independent executions over the same observation history must always
produce identical candidate sets.

---

# Validation Metrics

The following metrics will be collected.

Total Broken Swings

Candidate Count

Reduction Percentage

Latest Swing Percentage

Superseded Swing Percentage

Median Candles To Break

Average Candles To Break

---

# Success Criteria

The filter should significantly reduce the candidate space while
remaining completely deterministic.

A successful filter does **not** prove BOS.

It only identifies promising break events for further semantic analysis.

---

# Failure Criteria

The hypothesis should be rejected if any of the following occur.

- Candidate reduction is negligible.
- Candidate selection appears random.
- Candidate events clearly include large numbers of ordinary swing breaks.
- Historical inspection shows little relationship to structural change.

---

# Promotion Policy

This filter shall not become part of the ontology until experimental
validation demonstrates that it provides meaningful discriminatory power.

If the hypothesis is rejected,

it will be archived and replaced by the next experimental filter.

---

# Scope

This document defines only the first candidate filter.

It does not define

- BOS
- CHOCH
- Expansion
- Protected Swings
- Market Structure

Those concepts remain independent of this experiment.

---

# Current Status

Hypothesis

Not Validated

Not Implemented

Pending Experimental Evaluation