# Market Interpretation Architecture

## Purpose

This document defines the Market Interpretation Layer for Theory 1.0.

The Market Interpretation Layer consumes the immutable
CanonicalMarketModel and produces a theory-dependent understanding of
the current market.

It is the bridge between objective market facts and trading decisions.

---

# 1. Architectural Principle

The ontology answers:

> What objectively exists?

Market Interpretation answers:

> What do those objective facts imply?

Interpretation never changes the ontology.

Different theories may interpret the same ontology differently.

---

# 2. Position in the Architecture

Live Market
        │
        ▼
ObservationHistory
        │
        ▼
Semantic Construction
        │
        ▼
CanonicalMarketModel
        │
        ▼
Market Interpretation
        │
        ▼
Trade Candidate Generation
        │
        ▼
Risk
        │
        ▼
Execution

---

# 3. Responsibilities

Market Interpretation is responsible for:

- evaluating market context
- determining structural implications
- evaluating directional bias
- evaluating liquidity context
- measuring structural confidence

Market Interpretation is not responsible for:

- detecting swings
- constructing ontology
- generating orders
- position sizing
- broker communication

---

# 4. Input

Market Interpretation consumes exactly one object.

CanonicalMarketModel

The CanonicalMarketModel already contains:

- ObservationHistory
- Swings
- StructureEvents
- ProtectedSwings
- Expansions
- OriginRegions
- FairValueGaps
- OrderBlocks

No additional market reconstruction is permitted.

---

# 5. Output

Market Interpretation produces one immutable object.

MarketInterpretation

Example:

MarketInterpretation

Market Bias

Trend Strength

Liquidity Context

Structural Alignment

Confidence

This object becomes the input for Trade Candidate Generation.

---

# 6. Interpretation is Theory

Ontology is objective.

Interpretation is subjective.

Example

Ontology

Expansion exists.

Interpretation

Bullish continuation is likely.

Another theory may interpret the same Expansion differently.

This is expected.

---

# 7. Core Interpretation Questions

Every theory should answer the same questions.

Question 1

What is the current market bias?

Question 2

How strong is the current structure?

Question 3

Is market structure aligned?

Question 4

Where is liquidity located?

Question 5

How confident is this interpretation?

Theory-specific implementations may answer differently.

---

# 8. Market Bias

Market Bias represents directional preference.

Examples

Bullish

Bearish

Neutral

Bias is an interpretation.

Bias is not an ontology object.

---

# 9. Trend Strength

Trend Strength represents the quality of directional movement.

Examples

Weak

Moderate

Strong

Trend Strength is derived from ontology.

It is never stored in ontology.

---

# 10. Structural Alignment

Structural Alignment measures whether semantic constructs support the
same directional interpretation.

Examples

Expansion

Origin Region

Fair Value Gap

Order Block

These may all support one directional narrative.

Alignment is an interpretation.

---

# 11. Liquidity Context

Liquidity Context describes the relationship between current market
structure and nearby liquidity.

Examples

Liquidity Above

Liquidity Below

Balanced

Liquidity Context is theory-dependent.

---

# 12. Confidence

Confidence measures how strongly the interpretation supports a market
hypothesis.

Confidence should be explainable.

Confidence is not probability.

Confidence is a scoring mechanism defined by the active theory.

---

# 13. Explainability

Every MarketInterpretation must explain itself.

Example

Bias

Bullish

Reasons

✓ Bullish Expansion

✓ Protected Swing intact

✓ Bullish Order Block

✓ Active Fair Value Gap

✓ Structural Alignment

Interpretations should never be opaque.

---

# 14. Multiple Theories

Theory 1

CanonicalMarketModel

↓

ICT Interpretation

↓

MarketInterpretation

Theory 2

CanonicalMarketModel

↓

Wyckoff Interpretation

↓

MarketInterpretation

The ontology remains unchanged.

Only interpretation changes.

---

# 15. Multiple Timeframes

Market Interpretation should eventually support multiple timeframes.

Example

Weekly

↓

Daily

↓

4 Hour

↓

1 Hour

↓

15 Minute

↓

5 Minute

Interpretation should combine multiple semantic models.

Semantic construction remains independent for each timeframe.

---

# 16. Separation of Responsibilities

Semantic Construction

Produces objective market knowledge.

Market Interpretation

Produces theory-dependent market understanding.

Trade Candidate Generation

Produces possible trades.

Risk

Evaluates exposure.

Execution

Places orders.

Each layer has exactly one responsibility.

---

# 17. Dependency Rules

ObservationHistory

↓

Semantic Construction

↓

CanonicalMarketModel

↓

Market Interpretation

↓

Trade Candidate Generation

↓

Risk

↓

Execution

Reverse dependencies are prohibited.

---

# 18. Design Principles

Market Interpretation must be:

- deterministic
- explainable
- immutable
- modular
- theory-independent
- testable

Interpretation consumes ontology.

Interpretation never modifies ontology.

---

# 19. Future Extensions

Future versions may introduce:

- multiple interpretation engines
- AI-assisted interpretation
- statistical interpretation
- ensemble interpretation
- confidence calibration

These extensions must preserve the architectural boundary.

---

# 20. Theory 1.0 Freeze

Theory 1.0 freezes the role of Market Interpretation.

It exists to transform objective semantic facts into
theory-dependent market understanding.

It never:

- creates ontology
- places trades
- manages risk
- communicates with brokers

Market Interpretation is the reasoning layer between
market knowledge and trading decisions.