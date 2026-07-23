# BOS_DETECTION_ALGORITHM.md

# Institutional Trading AI
## Theory 1.0
## Break of Structure (BOS) Detection Algorithm

---

# 1. Purpose

This document specifies the canonical algorithm for detecting
Break of Structure (BOS) candidates.

It is implementation independent.

No Python-specific behavior is defined here.

This document defines only semantic behavior.

---

# 2. Objective

Detect structural continuation events from already confirmed swings.

A BOS is **not** a candle.

A BOS is **not** a swing.

A BOS is the semantic event representing continuation of an existing
market structure.

---

# 3. Position in Ontology

```
ObservationHistory

↓

Confirmed Swings

↓

BOS Candidate Detection

↓

Confirmation Policy

↓

Structure Event (BOS)
```

---

# 4. Inputs

The algorithm receives

```
ObservationHistory

+

Confirmed Swings
```

Confirmed Swings must already be chronologically ordered.

---

# 5. Outputs

Returns

```
tuple[StructureEventCandidate]
```

Only BOS candidates are produced.

Confirmation is performed separately.

---

# 6. Preconditions

The following must exist

- ObservationHistory
- Confirmed Swings

Otherwise

```
No candidates
```

---

# 7. Eligible Swings

Only confirmed swings participate.

No provisional swings.

No candidate swings.

---

# 8. Bullish BOS

Definition

A Bullish BOS occurs when price closes above
a previous confirmed Swing High.

---

# 9. Bearish BOS

Definition

A Bearish BOS occurs when price closes below
a previous confirmed Swing Low.

---

# 10. Detection Strategy

The detector operates only on confirmed swings.

Pseudo workflow

```
For each confirmed swing

↓

Search forward through candles

↓

Look for structural break

↓

Create candidate

↓

Continue
```

---

# 11. Bullish BOS Algorithm

For every confirmed Swing High

Search every candle after the swing confirmation.

If

```
Close > Swing High Price
```

Then

Create Bullish BOS Candidate.

Stop searching for this swing.

Continue to next Swing High.

---

# 12. Bearish BOS Algorithm

For every confirmed Swing Low

Search every candle after swing confirmation.

If

```
Close < Swing Low Price
```

Then

Create Bearish BOS Candidate.

Stop searching for this swing.

Continue to next Swing Low.

---

# 13. Confirmation Candle

Search begins only after

```
Swing Confirmation Candle
```

Never before.

This prevents look-ahead bias.

---

# 14. Break Condition

Bullish

```
Close > Swing High
```

Bearish

```
Close < Swing Low
```

Strict inequality.

---

# 15. Wick Rule

Highs and lows alone do not confirm BOS.

Example

```
High > Swing High

Close < Swing High
```

Result

```
Not BOS
```

Only candle close confirms.

---

# 16. Equal High / Equal Low

Equal values never produce BOS.

```
Close == Swing High
```

Not BOS.

```
Close == Swing Low
```

Not BOS.

---

# 17. First Break Wins

Only the first confirmed break of a swing
creates a BOS candidate.

Later candles breaking the same level
are ignored.

---

# 18. Candidate Fields

Each candidate contains

```
event_type

direction

timestamp

candle_index

broken_swing_index

base_swing_index

price

displacement
```

---

# 19. Event Type

Always

```
BOS
```

CHOCH is handled by a separate algorithm.

---

# 20. Direction

Bullish

```
BULLISH
```

Bearish

```
BEARISH
```

---

# 21. Timestamp

The timestamp is taken from the candle that
first confirms the break.

Never from the swing.

---

# 22. Candle Index

The candle index is the breaking candle.

Never the swing index.

---

# 23. Broken Swing Index

Reference to the Swing being broken.

---

# 24. Base Swing Index

The originating Swing from which the move
started.

Version 1

```
Same as broken swing
```

Later versions may distinguish these.

---

# 25. Price

Bullish

Closing price of the break candle.

Bearish

Closing price of the break candle.

---

# 26. Displacement

Version 1

```
abs(
Close
-
Swing Price
)
```

Future versions may use ATR-normalized
displacement.

---

# 27. Duplicate Prevention

A swing may produce only one BOS candidate.

---

# 28. Ordering

Candidates are ordered by candle index.

Ascending.

---

# 29. Complexity

Given

```
N observations

M swings
```

Worst case

```
O(M × N)
```

Future versions may optimize.

Correctness has priority over performance.

---

# 30. Responsibilities

Candidate Detector

Must

- iterate swings
- search forward
- detect breaks
- construct candidates

Must Not

- confirm candidates
- assign IDs
- determine protected swings
- classify CHOCH

---

# 31. Non-Responsibilities

The detector never

- determines trend
- creates Protected Swings
- creates Expansions
- creates Origin Regions
- creates Fair Value Gaps
- updates Market State

---

# 32. Invariants

Every BOS candidate satisfies

- references one confirmed swing
- exactly one direction
- exactly one timestamp
- exactly one candle index
- immutable
- chronologically ordered

---

# 33. Future Extensions

Later versions may include

- displacement thresholds
- ATR filters
- minimum impulse requirements
- volume confirmation
- liquidity sweep filtering
- internal vs external BOS
- multi-timeframe confirmation

These are outside Theory 1.0.

---

# 34. Summary

```
ObservationHistory

        +

Confirmed Swings

        ↓

Iterate Swings

        ↓

Search Forward

        ↓

Close Beyond Swing

        ↓

Create BOS Candidate

        ↓

Confirmation Policy

        ↓

Immutable Structure Event
```

The BOS detector is therefore a deterministic semantic transformation
from confirmed swings and market observations into candidate
Break of Structure events.