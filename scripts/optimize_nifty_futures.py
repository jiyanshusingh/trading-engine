from __future__ import annotations

import json
import numpy as np
import pandas as pd
import itertools
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, ".")

BEST_CONFIG = None
BEST_METRIC = -float('inf')
SEARCH_LOG = []

# NIFTY futures constants
LOT_SIZE = 65
CONTRACT_MULTIPLIER = 65
FNO_CAPITAL = 160000.0
STT_PCT = 0.01
EXCHANGE_FEE_PCT = 0.0002
SEBI_FEE_PCT = 0.0001
GST_PCT = 18.0
def _trade_cost(entry, exit, qty, direction):
    """Futures cost model."""
    buy_value = min(entry, exit) * qty
    sell_value = max(entry, exit) * qty
    turnover = entry * qty + exit * qty
    stt = sell_value * STT_PCT / 100
    exchange_fee = turnover * EXCHANGE_FEE_PCT / 100
    sebi = turnover * SEBI_FEE_PCT / 100
    brokerage = 20.0
    gst = brokerage * GST_PCT / 100
    return round(stt + exchange_fee + sebi + brokerage + gst, 2)
def run_backtest(config):
    """Run a single backtest with the given configuration."""
    import os
    os.environ['NIFTY_FUTURES_LONG_MIN_SCORE'] = str(config["LONG_MIN_SCORE"])
    os.environ['NIFTY_FUTURES_SHORT_MIN_SCORE'] = str(config["SHORT_MIN_SCORE"])
    
    from scripts.backtest_nifty_futures import run_backtest as run_bt
    
    # Load data
    from data.downloader.data_registry import get_bars
    df = get_bars("^NSEI", "15m", 2000)
    if df is None or len(df) < 200:
        raise ValueError("Insufficient data")
    
    # Run backtest
    result = run_bt(df, 
                    sl_mult=config["sl_mult"], 
                    tp_mult=config["tp_mult"],
                    days=365)
    
    return result
def optimize_thresholds():
    """Optimize score thresholds and SL/TP ratios."""
    global BEST_METRIC, BEST_CONFIG, SEARCH_LOG
    
    print("Starting parameter optimization...")
    
    # Parameter ranges - focused on finding net-positive after costs
    long_threshes = [60, 65, 70, 75, 80]
    short_threshes = [40, 45, 50, 55, 60]
    sl_multipliers = [0.3, 0.5, 0.8, 1.0]
    tp_multipliers = [3.0, 4.0, 5.0, 6.0]
    
    total_combos = len(long_threshes) * len(short_threshes) * len(sl_multipliers) * len(tp_multipliers)
    print(f"Testing {total_combos} parameter combinations...")
    
    combo_count = 0
    for long_thresh in long_threshes:
        for short_thresh in short_threshes:
            for sl_mult in sl_multipliers:
                for tp_mult in tp_multipliers:
                    combo_count += 1
                    params = {
                        "LONG_MIN_SCORE": long_thresh,
                        "SHORT_MIN_SCORE": short_thresh,
                        "sl_mult": sl_mult,
                        "tp_mult": tp_mult,
                    }
                    
                    print(f"\n[{combo_count}/{total_combos}] Testing: LONG={long_thresh}, SHORT={short_thresh}, SL={sl_mult}, TP={tp_mult}")
                    
                    try:
                        result = run_backtest(params)
                        stats = result.get("stats", {})
                        net_pnl = stats.get("net_pnl", 0)
                        max_drawdown = stats.get("max_drawdown", 1)
                        return_pct = stats.get("return_pct", 0)
                        trades = stats.get("total_trades", 0)
                        
                        # Calculate Sharpe-like metric (reward per unit of risk)
                        if max_drawdown > 0:
                            metric = (return_pct - max_drawdown) / max_drawdown
                        else:
                            metric = return_pct
                        
                        log_entry = {
                            "params": params,
                            "trades": trades,
                            "win_rate": stats.get("win_rate_pct", 0),
                            "net_pnl": net_pnl,
                            "max_drawdown": max_drawdown,
                            "return_pct": return_pct,
                            "metric": metric
                        }
                        
                        SEARCH_LOG.append(log_entry)
                        
                        if metric > BEST_METRIC:
                            BEST_METRIC = metric
                            BEST_CONFIG = params.copy()
                            print(f"  NEW BEST: Metric={metric:.3f}, ROI={return_pct:.1f}%, Trades={trades}")
                        
                    except Exception as e:
                        print(f"  ERROR: {e}")
                        continue
    
    return SEARCH_LOG, BEST_CONFIG, BEST_METRIC
def main():
    print("=" * 80)
    print("NIFTY Futures Strategy Parameter Optimization")
    print("=" * 80)
    
    # Run parameter optimization
    log, best_config, best_metric = optimize_thresholds()
    
    # Save results
    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "search_space": {
            "LONG_MIN_SCORE": [60, 65, 70, 75, 80],
            "SHORT_MIN_SCORE": [40, 45, 50, 55, 60],
            "sl_mult": [0.3, 0.5, 0.8, 1.0],
            "tp_mult": [3.0, 4.0, 5.0, 6.0],
        },
        "results": {
            "best_config": best_config,
            "best_metric": best_metric,
            "all_searches": log
        }
    }
    
    out_path = Path("data/optimization_results_nifty_futures.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nOptimization results saved to {out_path}")
    
    # Print summary
    print("\n" + "=" * 80)
    print("OPTIMIZATION COMPLETE")
    print("=" * 80)
    if best_config is not None:
        print(f"Best Configuration:")
        print(f"  LONG_MIN_SCORE: {best_config['LONG_MIN_SCORE']}")
        print(f"  SHORT_MIN_SCORE: {best_config['SHORT_MIN_SCORE']}")
        print(f"  SL multiplier: {best_config['sl_mult']}")
        print(f"  TP multiplier: {best_config['tp_mult']}")
        print()
        # Find best run
        for entry in log:
            if (entry['params']['LONG_MIN_SCORE'] == best_config['LONG_MIN_SCORE'] and
                entry['params']['SHORT_MIN_SCORE'] == best_config['SHORT_MIN_SCORE'] and
                entry['params']['sl_mult'] == best_config['sl_mult'] and
                entry['params']['tp_mult'] == best_config['tp_mult']):
                print(f"  ROI: {entry['return_pct']:.1f}%")
                print(f"  Max Drawdown: {entry['max_drawdown']:.1f}")
                print(f"  Net P&L: ₹{entry['net_pnl']:,.0f}")
                print(f"  Trades: {entry['trades']}")
            break
    
    return best_config
if __name__ == "__main__":
    main()
