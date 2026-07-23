"""
Multi-stock backtest — runs WalkForwardBacktest on all 30 cached NSE symbols.

Usage:
    .venv/bin/python scripts/run_backtest_portfolio.py
    .venv/bin/python scripts/run_backtest_portfolio.py --timeframe 1h --days 200
    .venv/bin/python scripts/run_backtest_portfolio.py --timeframe 15m 1h --intraday
"""

from __future__ import annotations

import argparse
import logging
import sys as _sys
from pathlib import Path

_sys.path.insert(0, ".")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

from data.downloader.watched_symbols import SYMBOLS
from scripts.backtest import (
    WalkForwardBacktest,
    fetch_data,
    resolve_upstox_key,
    _normalize_timestamp_tz,
    BacktestSummary,
    WINDOW_SIZE,
)

# Lookback mapping: longer timeframes need more calendar days
_ALL_TIMEFRAMES = ["1m", "15m", "1h", "1d"]

_SYMBOLS_OVERRIDE: list[str] | None = None  # set via --symbols

_LOOKBACK_MAP = {
    "1m": 15,
    "5m": 60,
    "15m": 120,
    "30m": 150,
    "1h": 200,
    "2h": 300,
    "4h": 365,
    "1d": 365,
}


def _lookback_for(timeframe: str, user_days: int | None) -> int:
    if user_days is not None:
        return user_days
    return _LOOKBACK_MAP.get(timeframe, 120)


def _run_timeframe(
    tf: str,
    days: int,
    intraday: bool,
    force_strategy: str | None = None,
    tuning_override: dict | None = None,
    use_whitelist: bool = False,
    provider_type: str = "upstox",
    cache_only: bool = False,
    multi_tf_filter: bool = True,
) -> list[BacktestSummary]:
    import pandas as pd

    label = "INTRADAY" if intraday else "SWING"

    symbols = _SYMBOLS_OVERRIDE if _SYMBOLS_OVERRIDE else SYMBOLS
    if use_whitelist:
        from config.symbol_whitelist import whitelist_for
        wl = whitelist_for(tf, intraday)
        if wl:
            symbols = [s for s in symbols if s in wl]
        else:
            print(f"  ⚠ No whitelist configured for {tf}/{label.lower()} — running full universe")

    print("=" * 70)
    print(f"  PORTFOLIO BACKTEST — {len(symbols)} Symbols"
          f"{' (WHITELIST)' if use_whitelist else ''}")
    print(f"  Timeframe: {tf:>3}  |  Lookback: {days}d  |  Mode: {label}  |  Provider: {provider_type}")
    print("=" * 70)

    results: list[BacktestSummary] = []
    total = len(symbols)

    for idx, sym in enumerate(symbols, 1):
        name = f"{sym}"

        # Upstox needs a resolved instrument key; other providers read the
        # local parquet cache (cache-first) and don't require a key, so they
        # can run the full expanded universe without API lookups.
        if provider_type == "upstox":
            instr_key = resolve_upstox_key(f"{sym}.NS", "upstox")
            if instr_key == f"{sym}.NS":
                print(f"  [{idx}/{total}] {sym:18s} → SKIP (no instrument key)")
                continue
        else:
            instr_key = f"{sym}.NS"

        print(f"  [{idx}/{total}] {sym:18s} → ", end="", flush=True)

        try:
            bt = WalkForwardBacktest(
                instr_key, name, tf, provider_type,
                intraday_mode=intraday,
                force_strategy=force_strategy,
                tuning_override=tuning_override,
                cache_only=cache_only,
                multi_tf_filter=multi_tf_filter,
            )
            summary = bt.run(days=days)
            summary.name = name

            if summary.total_trades > 0:
                print(f"✓ {summary.total_trades:3d} trades  "
                      f"WR={summary.win_rate:5.1f}%  "
                      f"PF={summary.profit_factor:6.2f}  "
                      f"avgR={summary.avg_r:+6.2f}  "
                      f"PnL={summary.total_pnl_pct:+7.2f}%")
            else:
                print("— No trades")
            results.append(summary)

        except Exception as e:
            print(f"✗ ERROR: {e}")

    return results


def _print_report(results: list[BacktestSummary], tf: str, suffix: str = "") -> None:
    import pandas as pd

    if not results:
        print("  No results.")
        return

    rows = []
    for s in results:
        rows.append({
            "symbol": getattr(s, "name", s.symbol),
            "timeframe": tf,
            "trades": s.total_trades,
            "wins": s.wins,
            "losses": s.losses,
            "win_rate": round(s.win_rate, 1),
            "avg_r": round(s.avg_r, 2),
            "profit_factor": round(s.profit_factor, 2),
            "total_pnl_pct": round(s.total_pnl_pct, 2),
            "max_dd": round(s.max_drawdown, 2),
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("profit_factor", ascending=False)

    print(f"\n  {'Symbol':18s} {'Tr':4s} {'WR':6s} {'PF':7s} {'avgR':7s} {'PnL%':8s} {'MaxDD':7s}")
    print(f"  {'─'*18} {'─'*4} {'─'*6} {'─'*7} {'─'*7} {'─'*8} {'─'*7}")
    for _, r in df.iterrows():
        print(f"  {r['symbol']:18s} {r['trades']:4d} {r['win_rate']:5.1f}% "
              f"{r['profit_factor']:7.2f} {r['avg_r']:+6.2f} {r['total_pnl_pct']:+7.2f}% "
              f"{r['max_dd']:6.1f}%")

    total_trades = df["trades"].sum()
    total_wins = df["wins"].sum()
    total_losses = df["losses"].sum()
    weighted_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
    positive_symbols = (df["profit_factor"] >= 1.3).sum()
    negative_symbols = (df["profit_factor"] < 1.0).sum()

    print(f"\n  {'─'*57}")
    print(f"  TOTAL: {len(results)} symbols  "
          f"{total_trades} trades  "
          f"WR={weighted_wr:.1f}%  "
          f"{positive_symbols} profitable  "
          f"{negative_symbols} unprofitable")

    # Save per-timeframe report
    import json as _json, os as _os
    _os.makedirs("data", exist_ok=True)
    path = f"data/backtest_portfolio_{tf}{suffix}.json"
    with open(path, "w") as f:
        _json.dump(df.to_dict(orient="records"), f, indent=2)
    print(f"\n  Saved to {path}")


def _save_trades(results: list[BacktestSummary], tf: str, suffix: str = "") -> None:
    import json as _json, os as _os
    all_trades = []
    for s in results:
        for t in s.trades:
            features = dict(t.features) if t.features else {}
            features.pop("strategy", None)
            features.pop("direction", None)
            features.pop("timeframe", None)
            all_trades.append({
                "symbol": getattr(s, "name", s.symbol),
                "timeframe": tf,
                "day_type": t.day_type,
                "stock_type": t.stock_type,
                "strategy": t.strategy,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "entry_timestamp": t.entry_timestamp,
                "exit_price": t.exit_price,
                "exit_timestamp": t.exit_timestamp,
                "r_multiple": t.r_multiple,
                "pnl_pct": t.pnl_percent,
                "pnl_net": t.pnl_net,
                "result": t.result,
                "score": t.score,
                "features": features,
            })
    _os.makedirs("data", exist_ok=True)
    path = f"data/backtest_trades_{tf}{suffix}.json"
    with open(path, "w") as f:
        _json.dump(all_trades, f, indent=2)
    print(f"  Saved {len(all_trades)} detailed trades to {path}")


def main() -> None:
    global _SYMBOLS_OVERRIDE
    parser = argparse.ArgumentParser(description="Multi-stock portfolio backtest")
    parser.add_argument(
        "--timeframe", "-t", nargs="+", default=["15m"],
        choices=["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"],
        help="Timeframe(s) to backtest (default: 15m)",
    )
    parser.add_argument(
        "--all-timeframes", "-a", action="store_true",
        help="Run all 4 core timeframes: 1m, 15m, 1h, 1d",
    )
    parser.add_argument(
        "--intraday", "-i", action="store_true", default=True,
        help="Intraday mode — force-close at EOD (default: on)",
    )
    parser.add_argument(
        "--no-intraday", action="store_true",
        help="Disable intraday mode (allow overnight holds)",
    )
    parser.add_argument(
        "--days", "-d", type=int, default=None,
        help="Lookback days per timeframe (default: auto per timeframe)",
    )
    parser.add_argument(
        "--strategy", "-s", type=str, default=None,
        help="Force a specific strategy for all conditions (e.g. 'Institutional Probability')",
    )
    parser.add_argument(
        "--tuning-sl", type=float, default=None,
        help="Override sl_mult (e.g. 0.5 for tight stops)",
    )
    parser.add_argument(
        "--tuning-tp", type=float, default=None,
        help="Override tp_mult (e.g. 5.0 for wide targets)",
    )
    parser.add_argument(
        "--short-sl-mult", type=float, default=None,
        help="Override short_sl_mult (e.g. 3.0)",
    )
    parser.add_argument(
        "--short-tp-mult", type=float, default=None,
        help="Override short_tp_mult (e.g. 1.5)",
    )
    parser.add_argument(
        "--whitelist", "-w", action="store_true",
        help="Only trade symbols in the (timeframe, mode) expectancy whitelist",
    )
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Restrict to a custom symbol list (e.g. expanded universe)",
    )
    parser.add_argument(
        "--provider", choices=["upstox", "yfinance"], default="upstox",
        help="Data provider (default upstox). Use 'yfinance' to run the full "
             "expanded universe from the local parquet cache without Upstox keys.",
    )
    parser.add_argument(
        "--slippage", choices=["off", "default", "realistic"], default="default",
        help="Cost model: 'off' = zero costs (gross PnL), 'default' = realistic "
             "discount-broker costs already applied, 'realistic' = stress-test "
             "with wider slippage + full per-order brokerage.",
    )
    parser.add_argument(
        "--cache-only", action="store_true",
        help="Use only cached parquet data; no yfinance/Upstox network fallback")
    parser.add_argument(
        "--cache-dir", type=str, default=None,
        help="Override cache root (e.g. data/cache_yf for native 15m LONG validation)")
    parser.add_argument(
        "--out-suffix", type=str, default=None,
        help="Extra suffix for output JSON filenames (e.g. '_manual191') to "
             "avoid clobbering a concurrent run's results")
    parser.add_argument(
        "--no-multi-tf", action="store_true",
        help="Disable the higher-timeframe (htf_check) trend filter. Needed for "
             "counter-trend mean-reversion strategies whose entries fire against "
             "the prevailing trend (Phase 29).")
    args = parser.parse_args()

    # Override cache directory if requested (e.g. data/cache_yf for native 15m)
    if args.cache_dir:
        from data.downloader.data_registry import override_cache_dir
        _cache_ctx = override_cache_dir(Path(args.cache_dir))
        _cache_ctx.__enter__()
    else:
        _cache_ctx = None

    # Apply the --slippage cost-model choice to the backtest engine's module
    # globals. These are read at trade-close time, so reassigning them here
    # (after import) takes effect for the whole run. Default behaviour is
    # unchanged when --slippage is omitted.
    import scripts.backtest as _bt
    if args.slippage == "off":
        _bt._COSTS_ENABLED = False
    elif args.slippage == "realistic":
        _bt._COSTS_ENABLED = True
        _bt.SLIPPAGE_PCT = 0.1          # 0.1% per side (wider, illiquid names)
        _bt.BROKERAGE_PER_TRADE = 40.0  # ₹20 per order x 2 (entry + exit)
        _bt.STT_PCT = 0.1
        _bt.GST_PCT = 18.0
        _bt.EXCHANGE_FEE_PCT = 0.0001
    # "default" leaves the module constants as-is (already realistic).

    # Normalise --symbols: accept space- and/or comma-separated input, and strip
    # a trailing ".NS" so the loop can safely re-append it. Without this,
    # "--symbols A.NS,B.NS" was captured as a single bogus symbol (and
    # "--symbols A.NS" became "A.NS.NS"), silently falling back to the full
    # universe or resolving to no data.
    if args.symbols:
        _SYMBOLS_OVERRIDE = []
        for _tok in args.symbols:
            for _part in str(_tok).split(","):
                _part = _part.strip()
                if not _part:
                    continue
                if _part.endswith(".NS"):
                    _part = _part[:-3]
                _SYMBOLS_OVERRIDE.append(_part)
        if not _SYMBOLS_OVERRIDE:
            _SYMBOLS_OVERRIDE = None
    else:
        _SYMBOLS_OVERRIDE = None

    intraday = not args.no_intraday
    timeframes = _ALL_TIMEFRAMES if args.all_timeframes else args.timeframe

    tuning_override = None
    if args.tuning_sl is not None and args.tuning_tp is not None:
        tuning_override = {
            "sl_mult": args.tuning_sl,
            "tp_mult": args.tuning_tp,
            "atr_period": 14,
        }
        if args.short_sl_mult is not None:
            tuning_override["short_sl_mult"] = args.short_sl_mult
        if args.short_tp_mult is not None:
            tuning_override["short_tp_mult"] = args.short_tp_mult

    suffix = "_wl" if args.whitelist else ""
    if args.out_suffix:
        suffix += args.out_suffix
    for tf in timeframes:
        days = _lookback_for(tf, args.days)
        results = _run_timeframe(tf, days, intraday, force_strategy=args.strategy,
                                 tuning_override=tuning_override,
                                 use_whitelist=args.whitelist,
                                 provider_type=args.provider,
                                 cache_only=args.cache_only,
                                 multi_tf_filter=not args.no_multi_tf)
        _print_report(results, tf, suffix=suffix)
        _save_trades(results, tf, suffix=suffix)
        print()

    if _cache_ctx is not None:
        _cache_ctx.__exit__(None, None, None)


if __name__ == "__main__":
    main()
