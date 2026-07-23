# BOS Candidate Filters

## Status

**Research Document**

This document records evidence-driven candidate filters for detecting
Break of Structure (BOS).

The purpose is **not** to define the BOS algorithm.

The purpose is to identify objective filters that eliminate ordinary
broken swings while retaining structurally meaningful break events.

Only experimentally validated observations belong here.

---

# Research Principle

A filter may be promoted only if it satisfies:

1. Objective
2. Deterministic
3. Reproducible
4. Supported by evidence

No filter should be adopted because it "looks like ICT."

---

# Research Workflow

```
Observation

↓

Hypothesis

↓

Instrumentation

↓

Evidence

↓

Decision
```

Architecture must follow evidence.

Not the other way around.

---

# Observation 1

## Almost Every Swing Eventually Breaks

Dataset

```
Total Swings

110,797
```

Broken Swings

```
110,281
```

Approximately

```
99.5%+
```

of confirmed swings are eventually broken.

### Implication

Breaking a swing is **not sufficient** to define BOS.

Any BOS detector based solely on

```
Current High > Previous Swing High
```

will massively over-detect BOS.

### Status

Confirmed.

---

# Observation 2

## Structural Lifetime Differs

Broken swings naturally partition into two groups.

### Latest Swing

Median time to break

```
2 candles
```

### Superseded Swing

Median time to break

```
31 candles
```

This represents a significant behavioral difference.

### Implication

Structural age may contain useful information.

However,

this does **not** imply that superseded swings are more important.

It only establishes that they behave differently.

### Status

Confirmed.

---

# Observation 3

## Multiple Broken Swings Are Not Required

A break event may break

```
1
```

swing only.

Therefore,

breaking multiple historical swings is **not** a necessary condition
for BOS.

### Status

Confirmed.

---

# Observation 4

## BOS Occurs At A Break Event

A swing is historical.

A BOS occurs on a candle.

Therefore,

the primary research object is the **Break Event**, not the swing.

```
Swing

↓

Break Event

↓

Potential BOS
```

### Status

Working hypothesis.

---

# Candidate Filters

The following filters have **not** yet been validated.

---

## Filter A

Latest Same-Type Swing

Question

Does a valid BOS usually break the latest confirmed swing
of the same type?

Status

Unverified.

---

## Filter B

Break By Close

Question

Must a valid BOS close beyond the swing?

Status

Unverified.

---

## Filter C

Minimum Displacement

Question

Does a valid BOS require minimum displacement beyond
the broken swing?

Status

Unverified.

---

## Filter D

Expansion

Question

Must the break occur during an Expansion?

Status

Unverified.

---

## Filter E

Break Context

Question

Does the surrounding swing sequence determine whether
the break becomes BOS?

Status

Unverified.

---

# Rejected Ideas

The following hypotheses have been rejected by evidence.

---

## Every Broken Swing Is BOS

Rejected.

Reason

Almost every swing eventually breaks.

---

## Multiple Broken Swings Are Required

Rejected.

Reason

Single-swing break events exist.

---

# Current Research Question

The current objective is:

> Find the first deterministic filter that substantially reduces
> ordinary broken swings while preserving genuine BOS candidates.

No new ontology should be introduced until a candidate filter
is experimentally validated.

---

# Next Experiment

Investigate whether the latest confirmed swing of the same type
is preferentially selected during valid BOS events.

This experiment should be driven by data rather than theory.