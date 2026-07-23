purpose
The Order Block Engine identifies institutional order blocks from validated
Break of Structure (BOS) events.

The engine is responsible only for detecting and maintaining Order Blocks.

It does not detect BOS, CHOCH, Trend, Swings, or Liquidity.

Responsibilities
The engine SHALL:

✓ Detect Bullish Order Blocks
✓ Detect Bearish Order Blocks
✓ Store Order Block metadata
✓ Maintain Order Block state
✓ Validate Order Blocks

The engine SHALL NOT:

✗ Detect BOS
✗ Detect CHOCH
✗ Detect Swings
✗ Detect Trend
✗ Detect Liquidity
✗ Detect FVG

inputs
Guaranteed Inputs

• OHLC DataFrame

• Market Structure State

• Valid BOS Events

outputs
Order Block List

Each Order Block contains

• Type

• Origin Candle

• High

• Low

• Source BOS

• Current State

• Validation Status

assumptions
The Order Block Engine assumes

✓ Swings are correct.

✓ BOS events are already validated.

✓ Market Structure is frozen.

If these assumptions are violated,
the Order Block Engine is not responsible.

invariants
One Valid BOS
↓

Creates at most one Order Block.
Bullish BOS

↓

Cannot create Bearish Order Block.
Bullish Order Block

↓

Must originate from a bearish candle.
Bearish Order Block

↓

Must originate from a bullish candle.

algorithm
Receive BOS Event

↓

Locate Impulse

↓

Locate Order Block Candle

↓

Create Order Block

↓

Validate Order Block

↓

Store Order Block