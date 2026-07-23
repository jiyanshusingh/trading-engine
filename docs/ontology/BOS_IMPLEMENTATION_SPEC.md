# BOS_IMPLEMENTATION_SPEC.md

# Institutional Trading AI
## Version 1.0
## Break of Structure (BOS) Implementation Specification

---

# Purpose

This document specifies the concrete implementation details for
Bullish and Bearish Break of Structure (BOS) candidate generation.

Unlike `BOS_DETECTION_ALGORITHM.md`, which defines the semantic theory,
this document defines exactly how the software implementation behaves.

This specification is normative.

---

# 1. Scope

Version 1 implements

- Bullish BOS
- Bearish BOS

Version 1 does **not** implement

- CHOCH
- Protected Swings
- Internal Structure
- External Structure
- Liquidity Sweeps
- Market State
- Multi-Timeframe Logic

---

# 2. Detector Inputs

The detector receives

```text
ObservationHistory

+

tuple[Swing]
```

Swings are assumed to be

- confirmed
- immutable
- chronological

---

# 3. Detector Output

Returns

```python
tuple[StructureEventCandidate]
```

Candidates are immutable.

Candidates are chronologically ordered.

---

# 4. Candidate Fields

Every candidate contains

```text
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

# 5. event_type

Always

```python
StructureEventType.BOS
```

CHOCH is produced by another detector.

---

# 6. direction

If SwingHigh is broken

```python
StructureDirection.BULLISH
```

If SwingLow is broken

```python
StructureDirection.BEARISH
```

---

# 7. timestamp

Timestamp of the candle that first closes beyond the swing.

Never the swing timestamp.

---

# 8. candle_index

Index of the candle confirming the break.

Example

```
Swing

index = 40

↓

Break candle

index = 58
```

Candidate

```
candle_index = 58
```

---

# 9. broken_swing_index

Index of the swing being broken.

Example

```
Swing High

index = 40
```

Candidate

```
broken_swing_index = 40
```

---

# 10. base_swing_index

Version 1

```
base_swing_index = broken_swing_index
```

Future versions may distinguish

- originating swing
- broken swing

Version 1 does not.

---

# 11. price

Version 1 stores

```text
Breaking candle CLOSE
```

Example

```
Swing High

100

↓

Close

101.25
```

Candidate

```
price = 101.25
```

---

# 12. displacement

Version 1

Bullish

```
close

-

swing_high
```

Bearish

```
swing_low

-

close
```

Always positive.

No ATR normalization.

No percentage normalization.

---

# 13. Bullish BOS Rule

Given

```
Swing High
```

Search forward beginning at

```
confirmation_index + 1
```

If

```
Close > SwingHigh
```

Create candidate.

Stop searching.

Continue to next swing.

---

# 14. Bearish BOS Rule

Given

```
Swing Low
```

Search forward beginning at

```
confirmation_index + 1
```

If

```
Close < SwingLow
```

Create candidate.

Stop searching.

Continue.

---

# 15. Wick Handling

Ignored.

Example

```
High

>

Swing High

Close

<

Swing High
```

No BOS.

Only CLOSE matters.

---

# 16. Equal Levels

Equal High

```
Close == Swing High
```

No BOS.

Equal Low

```
Close == Swing Low
```

No BOS.

Strict inequality only.

---

# 17. Duplicate Prevention

One swing

↓

Maximum one BOS candidate.

Subsequent breaks of the same swing

↓

Ignored.

---

# 18. Candidate Ordering

Candidates are sorted by

```
candle_index
```

Ascending.

---

# 19. Detector Responsibilities

The detector SHALL

- iterate confirmed swings
- inspect ObservationHistory
- identify break candles
- create BOS candidates
- maintain chronological ordering

The detector SHALL NOT

- confirm BOS
- reject BOS
- assign event IDs
- determine Protected Swings
- classify CHOCH
- infer market trend

---

# 20. Complexity

Given

```
N observations

M swings
```

Reference implementation

```
O(M × N)
```

Optimization is deferred.

Correctness has priority.

---

# 21. Failure Conditions

If ObservationHistory is None

↓

Raise ValueError.

If swings is None

↓

Raise ValueError.

Empty swings

↓

Return empty tuple.

---

# 22. Version 1 Test Matrix

The implementation SHALL satisfy

✓ Empty swings

✓ No BOS

✓ Single Bullish BOS

✓ Single Bearish BOS

✓ Multiple BOS

✓ Wick-only break rejected

✓ Equal High rejected

✓ Equal Low rejected

✓ Duplicate BOS prevented

✓ Chronological ordering preserved

---

# 23. Future Versions

Version 2

- CHOCH

Version 3

- Protected Swings

Version 4

- External Structure

Version 5

- Liquidity Validation

Version 6

- Multi-Timeframe Structure

---

# Summary

```text
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

Return Ordered Candidate Tuple
```

This specification defines the complete Version 1 implementation contract
for BOS candidate generation.