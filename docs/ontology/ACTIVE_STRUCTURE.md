# ACTIVE_STRUCTURE.md

# Institutional Trading AI
## Theory 1.0
## Active Structure Specification

---

# Purpose

This document defines the concept of **Active Structure**.

Active Structure is the missing semantic layer between

```
Confirmed Swings
```

and

```
Break of Structure (BOS).
```

Without Active Structure, every historical Swing High eventually
becomes a BOS, producing incorrect structural semantics.

This document specifies how the trading engine determines which
swings are structurally eligible to produce BOS events.

---

# Position in Ontology

```
ObservationHistory

↓

Confirmed Swings

↓

Active Structure

↓

BOS

↓

Protected Swings

↓

CHOCH

↓

Expansion
```

---

# Motivation

Confirmed Swings represent local market turning points.

They do **not** represent the current market structure.

Only a subset of confirmed swings are structurally active.

---

# Definition

An **Active Structure** is the currently valid structural reference
used for future Break of Structure detection.

It is the only structure eligible to generate BOS.

---

# Core Principle

Every confirmed swing exists.

Not every confirmed swing is structurally active.

---

# Structural Eligibility

A swing is eligible for BOS detection only while it remains active.

Inactive swings cannot generate new BOS events.

---

# Active Swing

An Active Swing satisfies all of the following:

- confirmed
- chronologically valid
- not replaced
- not consumed
- currently represents market structure

---

# Inactive Swing

A swing becomes inactive when

- replaced by a newer structural swing
- consumed by BOS
- invalidated by future semantic rules

---

# Active High

An Active High is the current structural resistance.

Bullish BOS may occur only above the Active High.

---

# Active Low

An Active Low is the current structural support.

Bearish BOS may occur only below the Active Low.

---

# Initial State

Before any refinement,

the first confirmed High becomes

```
ACTIVE HIGH
```

the first confirmed Low becomes

```
ACTIVE LOW
```

---

# Replacement Rule

When a newer confirmed structural High appears

↓

Current Active High

↓

becomes

```
REPLACED
```

↓

New High becomes

```
ACTIVE
```

The same rule applies for lows.

---

# Consumption Rule

When BOS occurs

↓

Active Swing

↓

becomes

```
CONSUMED
```

Consumed swings never generate another BOS.

---

# Active Structure State Machine

Every structural swing follows

```
CONFIRMED

↓

ACTIVE
```

then

either

```
ACTIVE

↓

REPLACED
```

or

```
ACTIVE

↓

BROKEN

↓

CONSUMED
```

---

# State Definitions

## CONFIRMED

Swing exists.

Not yet participating in structure.

---

## ACTIVE

Current structural reference.

Eligible for BOS.

---

## BROKEN

Price has produced a valid BOS.

---

## CONSUMED

Structure advanced.

Swing permanently retired.

---

## REPLACED

A newer structural swing supersedes it.

Cannot produce BOS.

---

# Structural Lifetime

```
Confirmed

↓

Active

↓

Broken

↓

Consumed
```

or

```
Confirmed

↓

Active

↓

Replaced
```

No other transitions exist in Version 1.

---

# Active High Example

```
High A

↓

High B

↓

High C
```

Current Active High

```
High C
```

High A

```
Inactive
```

High B

```
Inactive
```

---

# BOS Eligibility

Given

```
High A

High B

High C
```

Only

```
High C
```

may produce Bullish BOS.

---

# Multiple Historical Highs

Current Version

```
Break

↓

BOS

for

High A

High B

High C
```

Active Structure Version

```
Break

↓

BOS

for

High C only
```

---

# Chronological Rule

Structure always advances forward.

Never backward.

```
Old Swing

↓

New Swing

↓

BOS
```

Never

```
New Swing

↓

Old Swing

↓

BOS
```

---

# Structural Consistency

At any moment

there exists

at most

```
One Active High
```

and

```
One Active Low
```

---

# Responsibilities

Active Structure SHALL

- determine structural eligibility
- maintain active references
- retire obsolete swings
- expose active High
- expose active Low

---

# Non-Responsibilities

Active Structure SHALL NOT

- detect BOS
- detect CHOCH
- calculate displacement
- identify liquidity
- create Protected Swings
- build Expansions

---

# Relationship to BOS

BOS never searches every historical swing.

BOS searches only

```
Active High
```

or

```
Active Low
```

---

# Relationship to Protected Swing

Successful BOS

↓

Consumes Active Swing

↓

Creates candidate Protected Swing.

---

# Relationship to CHOCH

CHOCH compares breaks against

Active Structure.

Without Active Structure,

CHOCH has no semantic reference.

---

# Version 1 Simplification

Version 1 maintains

exactly

```
One Active High

One Active Low
```

No distinction between

- internal structure
- external structure
- nested structure

These are future extensions.

---

# Future Extensions

Future versions may include

- Internal Structure
- External Structure
- Multi-Timeframe Active Structure
- Liquidity-aware Active Structure
- Fractal Structure Hierarchies
- Protected Swing integration

---

# Invariants

The Active Structure model guarantees

- one active High maximum
- one active Low maximum
- chronological progression
- immutable historical swings
- no duplicate structural references

---

# Summary

```
Confirmed Swings

↓

Select Active High

↓

Select Active Low

↓

Monitor Active Structure

↓

Valid Break

↓

BOS

↓

Consume Active Structure

↓

Promote Next Active Structure
```

Active Structure is therefore the semantic layer that transforms a collection
of confirmed swings into the single structural references used for
institutional Break of Structure detection.