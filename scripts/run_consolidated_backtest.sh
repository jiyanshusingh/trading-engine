#!/bin/zsh
# Consolidated backtest: run all 3 deployed strategies sequentially with their
# exact live config (watchlists + per-symbol tunings + Phase 23 day-gates +
# Phase 24 confirmation gate). Cache-only, realistic costs, 730d swing.
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
DAYS=730
COMMON="--no-intraday --timeframe 15m --days ${DAYS} --slippage default --provider yfinance --cache-only"

MANUAL_SYMS=$(cat /tmp/manual_syms.txt)
RSM_SYMS=$(cat /tmp/rsm_syms.txt)
COMBINED_SYMS=$(cat /tmp/combined_syms.txt)

echo "################ 1/3 MANUAL INSTITUTIONAL ($(echo $MANUAL_SYMS | wc -w) syms) ################"
$PY scripts/run_backtest_portfolio.py $=COMMON \
  --strategy "Manual Institutional (time-gated)" \
  --tuning-sl 0.5 --tuning-tp 5.0 \
  --out-suffix _manual_final \
  --symbols ${=MANUAL_SYMS}

echo "################ 2/3 RELATIVE STRENGTH MOMENTUM ($(echo $RSM_SYMS | wc -w) syms) ################"
$PY scripts/run_backtest_portfolio.py $=COMMON \
  --strategy "Relative Strength Momentum" \
  --tuning-sl 2.0 --tuning-tp 4.0 \
  --out-suffix _rsm_final \
  --symbols ${=RSM_SYMS}

echo "################ 3/3 COMBINED SWING ($(echo $COMBINED_SYMS | wc -w) syms) ################"
$PY scripts/run_backtest_portfolio.py $=COMMON \
  --strategy "Combined Swing" \
  --tuning-sl 2.0 --tuning-tp 4.0 \
  --out-suffix _combined_final \
  --symbols ${=COMBINED_SYMS}

echo "################ ALL DONE ################"
