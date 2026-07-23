# Order Block Specification v1.0

## Definition

An Order Block is the price geometry produced by an Order Block Policy
from an Origin Region.

## Type

Value Object

## Relationships

Expansion
    ↓
Origin Region Policy
    ↓
Origin Region
    ↓
Order Block Policy
    ↓
Order Block

## Invariants

1. Every Order Block belongs to exactly one Origin Region.
2. Every Order Block is produced by exactly one Order Block Policy.
3. Order Blocks are immutable.
4. Identical inputs always produce identical Order Blocks.
5. low <= high

## Model

OrderBlock

- origin_region
- high
- low

## Current Policy

FullCandleOrderBlockPolicy

High = Candle High
Low  = Candle Low

Status: FROZEN