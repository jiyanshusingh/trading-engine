#!/bin/zsh
# Re-backtest the OOS-pruned Manual & RSM watchlists (Phase 27) to confirm net-positive.
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
COMMON="--no-intraday --timeframe 15m --days 730 --slippage default --provider yfinance --cache-only"

MANUAL_SYMS=$(cat /tmp/manual_pruned_syms.txt)
RSM_SYMS=$(cat /tmp/rsm_pruned_syms.txt)

echo "################ MANUAL PRUNED ($(echo $MANUAL_SYMS | wc -w) syms) ################"
$PY scripts/run_backtest_portfolio.py $=COMMON \
  --strategy "Manual Institutional (time-gated)" \
  --tuning-sl 0.5 --tuning-tp 5.0 \
  --out-suffix _manual_pruned \
  --symbols ${=MANUAL_SYMS}

echo "################ RSM PRUNED ($(echo $RSM_SYMS | wc -w) syms) ################"
$PY scripts/run_backtest_portfolio.py $=COMMON \
  --strategy "Relative Strength Momentum" \
  --tuning-sl 2.0 --tuning-tp 4.0 \
  --out-suffix _rsm_pruned \
  --symbols ${=RSM_SYMS}

echo "################ PRUNED BACKTEST DONE ################"
