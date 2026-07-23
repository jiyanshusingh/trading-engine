# STRUCTURE_EVENT_THEORY.md

# Institutional Trading AI
## Theory 1.0
## Structure Event Ontology

---

# 1. Purpose

A Structure Event represents a confirmed change or continuation of market
structure.

Structure Events are **semantic events**.

They are **not** price bars.

They are **not** swings.

They describe a structural relationship between confirmed swings.

Structure Events are produced only after Swing construction has completed.

---

# 2. Ontological Position

```
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
```

A Structure Event is therefore a higher-order semantic object.

---

# 3. Definition

A Structure Event is a confirmed break of a previously established swing level.

It represents either

- continuation of structure

or

- change of structure.

---

# 4. Types

Two event types exist.

## BOS

Break of Structure

Represents continuation.

Examples

Bullish

Higher High breaks previous High.

Bearish

Lower Low breaks previous Low.

---

## CHOCH

Change of Character

Represents reversal.

Examples

Bullish

Price breaks the last protected High.

Bearish

Price breaks the last protected Low.

---

# 5. Preconditions

Structure Events require

- confirmed ObservationHistory

- confirmed Swings

Without confirmed Swings there can be no Structure Events.

---

# 6. Inputs

The detector consumes

```
ObservationHistory

+

Confirmed Swings
```

It never consumes raw candles alone.

---

# 7. Event Components

Every Structure Event contains

```
event_id

event_type

direction

timestamp

candle_index

price

broken_swing_index

base_swing_index

displacement
```

---

# 8. Direction

Direction is determined by the broken swing.

Bullish

Break above structural High.

Bearish

Break below structural Low.

---

# 9. BOS Rules

Bullish BOS

Requirements

• Existing bullish structure

• Previous High exists

• Price closes above previous High

Result

Bullish BOS

---

Bearish BOS

Requirements

• Existing bearish structure

• Previous Low exists

• Price closes below previous Low

Result

Bearish BOS

---

# 10. CHOCH Rules

Bullish CHOCH

Requirements

• Existing bearish structure

• Protected High exists

• Price closes above Protected High

Result

Bullish CHOCH

---

Bearish CHOCH

Requirements

• Existing bullish structure

• Protected Low exists

• Price closes below Protected Low

Result

Bearish CHOCH

---

# 11. Confirmation Rule

A Structure Event is confirmed only after candle close.

Intrabar movement never confirms structure.

```
Close > High

Confirmed
```

```
Wick > High

Not confirmed
```

Same rule applies to bearish breaks.

---

# 12. Equal Highs / Equal Lows

Equal High

Not a break.

Equal Low

Not a break.

Strict inequality is required.

```
>

<
```

never

```
>=

<=
```

---

# 13. Valid Break

A valid break requires

```
Close

beyond

structural level
```

Merely touching the level is ignored.

---

# 14. Multiple Breaks

Only the first confirmed break creates an event.

Subsequent candles above the same level do not create additional BOS events.

---

# 15. Event Ordering

Events are strictly chronological.

```
Event 1

↓

Event 2

↓

Event 3
```

Event IDs increase monotonically.

---

# 16. Event Immutability

After creation

Structure Events never change.

Correction requires rebuilding the CanonicalMarketModel.

---

# 17. Structural Consistency

Impossible sequences are prohibited.

Example

```
Bullish BOS

↓

Bullish BOS

↓

Bearish CHOCH

↓

Bullish BOS
```

The Bullish BOS after Bearish CHOCH is invalid unless a new bullish structure has first been established.

---

# 18. Relationship to Swings

Structure Events never create Swings.

Swings create Structure Events.

Dependency

```
ObservationHistory

↓

Swings

↓

Structure Events
```

Never

```
ObservationHistory

↓

Structure Events

↓

Swings
```

---

# 19. Relationship to Protected Swings

Protected Swings are derived from confirmed Structure Events.

Dependency

```
Structure Events

↓

Protected Swings
```

---

# 20. Relationship to Expansions

Expansions begin only after valid BOS.

```
BOS

↓

Expansion
```

CHOCH never starts an Expansion directly.

---

# 21. Detector Responsibilities

The Candidate Detector

Must

• identify possible BOS

• identify possible CHOCH

• create candidates only

Must Not

• confirm

• reject

• score

• mutate market state

---

# 22. Confirmation Policy Responsibilities

Confirmation Policy

Must

• verify close beyond level

• verify displacement

• verify rule compliance

Must Not

• search for candidates

---

# 23. Builder Responsibilities

Builder

Must

• assign IDs

• construct immutable StructureEvent objects

• preserve chronological ordering

Must Not

• detect

• confirm

---

# 24. Invariants

Every Structure Event satisfies

- exactly one direction

- exactly one event type

- exactly one timestamp

- exactly one candle index

- immutable after creation

- references existing swings

---

# 25. Theory Summary

ObservationHistory

↓

Confirmed Swings

↓

Candidate Detection

↓

Confirmation Policy

↓

Immutable Structure Events

↓

CanonicalMarketModel

Structure Events are therefore semantic relationships between confirmed swings and constitute the second semantic layer of the Institutional Trading AI ontology.