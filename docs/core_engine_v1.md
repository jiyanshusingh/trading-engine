# Core Engine v1.0

## Status

Frozen

---

# Purpose

The Core Engine is responsible for transforming raw market price into an objective structural representation of the market.

It detects structural facts, converts those facts into immutable events, and derives the current market state.

The Core Engine does not generate trading signals.

Higher-level engines such as Segment Engine, Order Block Engine, Liquidity Engine, Fair Value Gap Engine, and Entry Engine consume the outputs of the Core Engine.

---

# Architecture

Price
    ↓
Data Engine
    ↓
Market Structure Engine
    ├── Swing Detection
    ├── Structure Classification
    ├── Trend Candidate
    ├── Protected Swings
    ├── BOS Detection
    └── CHOCH Detection
    ↓
Structure Event Engine
    ├── BOS Events
    └── CHOCH Events
    ↓
Market State Engine

---

# Layer Responsibilities

## Data Engine

Responsible for loading and preparing OHLCV market data.

Outputs:

- Open
- High
- Low
- Close
- Volume

Never performs structural analysis.

---

## Market Structure Engine

Responsible for identifying objective market structure.

Outputs:

- Swing Highs
- Swing Lows
- HH
- HL
- LH
- LL
- Trend Candidate
- Protected High
- Protected Low
- BOS
- CHOCH

Never creates events.

Never updates market state.

---

## Structure Event Engine

Responsible for converting structural facts into immutable events.

Outputs:

- BOS Events
- CHOCH Events

Never modifies market structure.

Never interprets trend.

---

## Market State Engine

Responsible for interpreting structural events.

Consumes:

- BOS Events
- CHOCH Events

Outputs:

- UNKNOWN
- UPTREND
- DOWNTREND
- TRANSITION

Never reads price directly.

Never detects structure.

---

# Core Domain Objects

## Swing

Represents a structural turning point.

Fields

- index
- price
- type

---

## Protected Swing

Represents the active structural swing that maintains the current trend.

Fields

- index
- price
- direction

---

## Structure Event

Represents an immutable structural event.

Common Fields

- event_id
- event_type
- direction
- timestamp
- candle_index
- broken_swing_index
- base_swing_index
- price
- valid
- metadata

---

# BOS Definition

Break Of Structure confirms continuation of the current trend.

Characteristics

- breaks a Continuation Swing
- confirms trend continuation
- does not invalidate trend

---

# CHOCH Definition

Change Of Character invalidates the current trend.

Characteristics

- breaks a Protected Swing
- invalidates the current trend
- moves market into Transition
- does not confirm a new trend

---

# Market States

Allowed States

- UNKNOWN
- UPTREND
- DOWNTREND
- TRANSITION

No additional states are permitted.

---

# Market State Transitions

UNKNOWN

Bullish BOS

↓

UPTREND

Bearish BOS

↓

DOWNTREND

---

UPTREND

Bullish BOS

↓

UPTREND

Bearish CHOCH

↓

TRANSITION

---

DOWNTREND

Bearish BOS

↓

DOWNTREND

Bullish CHOCH

↓

TRANSITION

---

TRANSITION

Bullish BOS

↓

UPTREND

Bearish BOS

↓

DOWNTREND

---

# Dependency Rules

Allowed

Price

↓

Market Structure

↓

Structure Events

↓

Market State

↓

Higher-Level Engines

Forbidden

Market State → Price

Structure Events → Candles

Higher-Level Engines → OHLC

Every layer may depend only on the layer immediately below it.

---

# Invariants

BOS breaks a Continuation Swing.

CHOCH breaks a Protected Swing.

A Protected Swing generates at most one CHOCH.

Market State depends only on structural events.

Events are immutable.

Historical events are never modified.

Engines never modify outputs produced by previous engines.

---

# Core Engine Scope

The Core Engine ends at Market State.

The following are outside the Core Engine:

- Segment Engine
- Order Block Engine
- Liquidity Engine
- Fair Value Gap Engine
- Mitigation Engine
- Entry Engine
- Risk Engine

These engines consume the outputs of the Core Engine.

---

# Version

Core Engine Version: 1.0

Status: Frozen