# Segment Specification v1.0

## Status

Frozen

---

# Purpose

A Segment represents a period of established directional structural control.

It is a historical structural entity constructed from Structure Events.

Segments are immutable records that describe when structural control began and when it ended.

Segments do not generate trading signals.

Higher-level engines such as Order Block Engine, Liquidity Engine, Fair Value Gap Engine, and Mitigation Engine consume Segments.

---

# Domain Classification

| Object | Classification |
|----------|---------------|
| BOS | Event |
| CHOCH | Event |
| Market State | State |
| Trend | State |
| Segment | Entity |

Segments are Entities because they have identity and history.

---

# Definition

A Segment is a period during which one side maintains confirmed structural control.

A Segment:

- begins with a BOS
- ends with a CHOCH
- may contain multiple continuation BOS events
- never changes direction

---

# Responsibilities

A Segment is responsible for representing:

- its identity
- its direction
- where structural control began
- where structural control ended

A Segment is NOT responsible for:

- runtime state
- transition state
- market interpretation
- order blocks
- liquidity
- fair value gaps

Those belong to other engines.

---

# Lifecycle

Segment creation:

UNKNOWN
↓
BOS
↓
Segment Created

---

Segment continuation:

Segment
↓
Continuation BOS
↓
Same Segment

---

Segment termination:

Segment
↓
CHOCH
↓
Segment Closed

---

Transition:

CHOCH
↓
No Active Segment

↓

Next BOS

↓

New Segment

---

# Runtime Ownership

Runtime state belongs to SegmentEngine.

SegmentEngine stores:

- active_segment
- next_segment_id
- segments

A Segment stores only historical information.

---

# Segment Model

Segment

- id
- direction
- start_event_id
- end_event_id
- start_index
- end_index

No runtime state is stored inside a Segment.

---

# Derived Properties

A Segment is considered open when:

end_event_id == None

A Segment is considered closed when:

end_event_id != None

These properties are derived.

They are not explicitly stored.

---

# Invariants

A Segment has exactly one direction.

A Segment has exactly one start event.

A Segment has at most one end event.

A Segment cannot change direction.

Segments never overlap.

There is at most one active Segment.

Historical Segments are immutable.

Continuation BOS never creates a new Segment.

CHOCH closes the active Segment.

CHOCH never creates a new Segment.

The first BOS after Transition creates the next Segment.

---

# Event Relationship

BOS

- creates a Segment if no active Segment exists
- otherwise belongs to the current Segment

CHOCH

- closes the current Segment
- never belongs to any Segment

---

# Dependency

Price
↓

Market Structure

↓

Structure Events

↓

Segment Engine

Segments are built exclusively from Structure Events.

SegmentEngine does not consume Market State.

---

# Scope

The Segment Engine ends with immutable Segment entities.

The following engines consume Segments:

- Order Block Engine
- Liquidity Engine
- Fair Value Gap Engine
- Mitigation Engine

---

# Version

Segment Specification Version: 1.0

Status: Frozen