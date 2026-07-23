"""
Phase 6 (corrected) — Walk-forward / out-of-sample validation.

FIXES the earlier leakage:
  1. The engine no longer sees future data (scripts/backtest.py now slices
     nifty_daily / stock_daily / nifty_intraday to point-in-time).
  2. THIS harness now uses NON-OVERLAPPING windows: train on an EARLIER
     period, build the whitelist, then test on a STRICTLY LATER, disjoint
     period. (Previously test ⊂ train, so it was in-sample.)

Usage
-----
  Single train/test pair:
    .venv/bin/python -m scripts.walkforward_validate --timeframe 1h --no-intraday \
        --train-start 2023-07-01 --train-end 2025-01-01 \
        --test-start 2025-01-01 --test-end 2026-07-10 \
        --sl 1.5 --tp 4.0

  Rolling walk-forward (N out-of-sample folds):
    .venv/bin/python -m scripts.walkforward_validate --timeframe 1h --no-intraday \
        --train-start 2023-07-28 --test-end 2024-12-31 --folds 3 \
        --symbols WIPRO,RELIANCE,ONGC,BSE,ADANIENT --sl 1.5 --tp 4.0

  Validate SHORT out-of-sample (sets INST_SHORT_MIN_SCORE=40, reports SHORT-only
  expectancy so the OOS edge of the short side can be judged on its own):
    .venv/bin/python -m scripts.walkforward_validate --timeframe 15m \
        --train-start 2023-07-28 --test-end 2026-07-10 --folds 3 \
        --symbols WIPRO,RELIANCE,ONGC,BSE,ADANIENT --sl 0.5 --tp 5.0 --shorts
"""

from __future__ import annotations

import argparse
import json
import os
import sys as _sys

_sys.path.insert(0, ".")

from datetime import datetime

from data.downloader.watched_symbols import SYMBOLS
from config.symbol_whitelist import MIN_PF, MIN_TRADES, bucket_key
# NOTE: scripts.backtest is imported lazily inside main() so that --shorts can
# set INST_SHORT_MIN_SCORE before the engine's module-level constants freeze.



def _dir_stats(trades: list, direction: str | None) -> dict:
    """Aggregate trade stats for one direction (LONG/SHORT/None=all).

    Mirrors backtest._aggregate but lets us isolate SHORT (or LONG) so the OOS
    report reflects only the side being validated.
    """
    primary = [t for t in trades if not t.is_benchmark]
    if direction is not None:
        primary = [t for t in primary if t.direction == direction]
    resolved = [t for t in primary
                if t.result in ("WIN", "LOSS", "CLOSE", "EXPIRED")
                and t.r_multiple is not None]
    if not resolved:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "avg_r": 0.0, "profit_factor": 0.0, "total_pnl_pct": 0.0}
    n = len(resolved)
    wins = [t for t in resolved
            if (t.result == "WIN") or (t.r_multiple or 0) > 0]
    losses = [t for t in resolved
              if (t.result == "LOSS") or (t.r_multiple or 0) <= 0]
    gross_win = sum(max(0.0, t.r_multiple) for t in resolved)
    gross_loss = sum(abs(min(0.0, t.r_multiple)) for t in resolved)
    pf = gross_win / gross_loss if gross_loss > 0 else 0.0
    pnl_pct = sum(t.pnl_percent or 0.0 for t in resolved)
    # NET expectancy: apply the backtest's per-trade cost (t.pnl_net_pct) and
    # express it in R (net return on notional / stop-distance fraction). This is
    # the number that actually matters for deployment — the headline `avg_r`
    # above is GROSS (costs excluded from t.r_multiple).
    net_r_list = []
    for t in resolved:
        ep = getattr(t, "entry_price", None)
        sl = getattr(t, "stop_loss", None)
        if ep and sl is not None and ep > 0:
            sl_frac = abs(ep - sl) / ep
            if sl_frac > 0:
                net_r_list.append((t.pnl_net_pct or 0.0) / 100.0 / sl_frac)
    net_avg_r = round(sum(net_r_list) / len(net_r_list), 3) if net_r_list else 0.0
    net_pnl_pct = round(sum(t.pnl_net_pct or 0.0 for t in resolved), 2)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_r": round(sum(t.r_multiple for t in resolved) / n, 3),
        "profit_factor": round(pf, 2),
        "total_pnl_pct": round(pnl_pct, 2),
        "net_avg_r": net_avg_r,
        "net_total_pnl_pct": net_pnl_pct,
    }


def _portfolio_stats(tf: str, intraday: bool, start: str, end: str,
                      sl: float, tp: float, symbols=None,
                      direction: str | None = None,
                       short_sl: float = 1.0, short_tp: float = 2.0,
                       short_open_only: bool = False,
                       require_down_day: bool = False) -> list[dict]:
    from data.downloader.data_registry import get_bars
    if symbols is None:
        from data.downloader.watched_symbols import SYMBOLS as symbols
    tuning = {"sl_mult": sl, "tp_mult": tp, "atr_period": 14,
              "short_sl_mult": short_sl, "short_tp_mult": short_tp,
              "short_open_only": short_open_only,
              "require_down_day": require_down_day}
    rows = []
    for sym in symbols:
        key = resolve_upstox_key(f"{sym}.NS", "upstox")
        if key == f"{sym}.NS":
            continue
        # Load the FULL cached series and slice to [start, end] ourselves so
        # the backtester's point-in-time logic has the right window.
        try:
            df = get_bars(sym, tf, 4000, live=False)
            if df is None or df.empty:
                continue
            df["timestamp"] = pd_to_ts(df["timestamp"])
            mask = (df["timestamp"] >= pd_Timestamp(start)) & (df["timestamp"] < pd_Timestamp(end))
            df = df[mask].reset_index(drop=True)
            if len(df) < 200:
                continue
        except Exception:
            continue
        try:
            # Pre-fetch NIFTY (15m + 1d) from the REAL cache, OUTSIDE the
            # scratch-cache override below. yfinance caps 15m at 60 days, so we
            # use the cached Upstox 729d series (data/cache/15m/^NSEI.parquet)
            # which covers the full historical window — this is what makes the
            # day-type classification correct for non-recent test windows.
            from scripts.backtest import fetch_data, _normalize_timestamp_tz
            nifty_15m = fetch_data("^NSEI", tf, "upstox", 2000)
            if nifty_15m is None:
                nifty_15m = fetch_data("^NSEI", tf, "yfinance", 2000)
            if nifty_15m is not None:
                nifty_15m = _normalize_timestamp_tz(nifty_15m)
            nifty_1d = fetch_data("^NSEI", "1d", "yfinance", 1825)
            if nifty_1d is not None:
                nifty_1d = _normalize_timestamp_tz(nifty_1d)

            # BANKNIFTY (15m + 1d) and VIX (1d) — same rationale as NIFTY: fetch
            # from the REAL cache (full 729d history) OUTSIDE the scratch override
            # so the richer regime classification works for any window.
            banknifty_15m = fetch_data("^NSEBANK", tf, "upstox", 2000)
            if banknifty_15m is None:
                banknifty_15m = fetch_data("^NSEBANK", tf, "yfinance", 2000)
            if banknifty_15m is not None:
                banknifty_15m = _normalize_timestamp_tz(banknifty_15m)
            banknifty_1d = fetch_data("^NSEBANK", "1d", "yfinance", 1825)
            if banknifty_1d is not None:
                banknifty_1d = _normalize_timestamp_tz(banknifty_1d)
            vix_1d = fetch_data("^INDIAVIX", "1d", "yfinance", 1825)
            if vix_1d is not None:
                vix_1d = _normalize_timestamp_tz(vix_1d)

            # Redirect the data-registry cache root to a scratch dir so the
            # sliced window is what the backtester reads, WITHOUT overwriting
            # the real data/cache (which was being destroyed on every run).
            from pathlib import Path
            from data.downloader import data_registry as _dr
            scratch = Path("data/cache_wf")
            scratch.mkdir(parents=True, exist_ok=True)
            tf_dir = _dr._INTERVAL_MAP.get(tf, tf)
            dest = scratch / tf_dir / f"{sym}.parquet"
            dest.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(dest, index=False)

            with _dr.override_cache_dir(scratch):
                bt = WalkForwardBacktest(
                    key, sym, tf, "upstox", intraday_mode=intraday,
                    force_strategy="Institutional Probability", tuning_override=tuning,
                    nifty_intraday=nifty_15m, nifty_daily=nifty_1d,
                    banknifty_intraday=banknifty_15m, banknifty_daily=banknifty_1d,
                    vix_daily=vix_1d,
                )
                s = bt.run(days=len(df))  # sliced file bounds the window
        except Exception:
            continue
        stats = _dir_stats(s.trades, direction)
        if stats["trades"] >= 1:
            rows.append({"symbol": sym, "timeframe": tf, **stats})
    return rows


def _build_whitelist_from(rows: list[dict], min_pf: float = MIN_PF,
                          min_trades: int = MIN_TRADES,
                          net_min: float = 0.0) -> list[str]:
    """Build the deployable whitelist.

    Symbols must clear the gross PF/trades gate AND be NET-profitable after
    costs on the train window (net_avg_r >= net_min). Selecting on net expectancy
    is what makes the OOS book actually tradeable — the old gross-PF gate hid
    symbols whose edge was eaten by transaction costs.
    """
    return [r["symbol"] for r in rows
            if r["profit_factor"] >= min_pf and r["trades"] >= min_trades
            and r.get("net_avg_r", 0.0) >= net_min]


def _fold_boundaries(start: str, end: str, n: int) -> list:
    """Chronological boundaries dividing [start, end] into n equal segments.
    Fold i (1..n) trains on [s0, s_i) and tests on [s_i, s_{i+1})."""
    s = pd_Timestamp(start)
    e = pd_Timestamp(end)
    return [s + (e - s) * i / n for i in range(n + 1)]


def _run_pair(tf, intraday, tr_s, tr_e, te_s, te_e, sl, tp, symbols, key,
              direction=None, min_pf: float = MIN_PF, min_trades: int = MIN_TRADES,
              short_sl: float = 1.0, short_tp: float = 2.0,
              net_min: float = 0.0, short_open_only: bool = False,
              require_down_day: bool = False):
    """Train on [tr_s,tr_e), build whitelist, report OOS on [te_s,te_e).

    The open-only gate (Phase A) is applied ONLY in the OOS test window — the
    whitelist is built on the full (ungated) train population so symbols with
    edge are still identified despite the gate's sparsity. This isolates the
    gate's effect as an added OOS filter.
    """
    train = _portfolio_stats(tf, intraday, tr_s, tr_e, sl, tp, symbols, direction,
                             short_sl, short_tp, short_open_only=False,
                             require_down_day=False)
    wl = _build_whitelist_from(train, min_pf, min_trades, net_min)
    print(f"  train [{tr_s} -> {tr_e}): {len(train)} syms tested, "
          f"{len(wl)} passed whitelist ({', '.join(wl) or '-'})")
    test = _portfolio_stats(tf, intraday, te_s, te_e, sl, tp, symbols, direction,
                            short_sl, short_tp, short_open_only,
                            require_down_day)
    test_wl = [r for r in test if r["symbol"] in wl]
    return wl, test_wl


def _report_oos(key: str, test_wl: list[dict]) -> None:
    tr = sum(r["trades"] for r in test_wl)
    if tr:
        wr = sum(r["wins"] for r in test_wl) / tr * 100
        exp = sum(r["avg_r"] * r["trades"] for r in test_wl) / tr
        pnl = sum(r["total_pnl_pct"] for r in test_wl)
        net_exp = sum(r["net_avg_r"] * r["trades"] for r in test_wl) / tr
        net_pnl = sum(r["net_total_pnl_pct"] for r in test_wl)
        prof = sum(1 for r in test_wl if r["profit_factor"] >= MIN_PF)
        net_prof = sum(1 for r in test_wl if r["net_avg_r"] > 0)
        print(f"  [OUT-OF-SAMPLE] {key}: {len(test_wl)} whitelisted symbols, "
              f"{tr} trades")
        print(f"    WR={wr:.1f}%  GROSS expectancy={exp:+.3f}R  "
              f"NET expectancy={net_exp:+.3f}R  "
              f"PF>=1.5 symbols={prof}/{len(test_wl)}  "
              f"net+ve symbols={net_prof}/{len(test_wl)}")
        print(f"    GROSS sumPnL%={pnl:+.1f}   NET sumPnL%={net_pnl:+.1f}")
        for r in test_wl:
            print(f"      {r['symbol']:10s} trades={r['trades']:4d}  "
                  f"WR={r['win_rate']:.1f}%  PF={r['profit_factor']:.2f}  "
                  f"GROSS exp={r['avg_r']:+.3f}R  NET exp={r['net_avg_r']:+.3f}R")
    else:
        print(f"  [OUT-OF-SAMPLE] {key}: no trades in test window for whitelist")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", "-t", required=True)
    ap.add_argument("--no-intraday", action="store_true")
    ap.add_argument("--train-start", default=None)
    ap.add_argument("--train-end", default=None)
    ap.add_argument("--test-start", default=None)
    ap.add_argument("--test-end", default=None)
    ap.add_argument("--sl", type=float, required=True)
    ap.add_argument("--tp", type=float, required=True)
    ap.add_argument("--short-sl", type=float, default=1.0,
                    help="SHORT stop multiplier (ATR). Default 1.0. "
                         "WARNING: position is capped at ₹50k, so a TIGHTER "
                         "stop raises reward/risk but a WIDER stop lowers it.")
    ap.add_argument("--short-tp", type=float, default=1.0,
                    help="SHORT target multiplier (scales the swing/ATR reward). "
                         "Default 1.0 (preserves prior behaviour). Raising this "
                         "boosts reward/risk (and net expectancy).")
    ap.add_argument("--short-open-only", action="store_true",
                    help="Phase A: restrict SHORT entries to the first 15m bar "
                         "(09:15). Session-timing analysis showed the SHORT edge "
                         "is entirely an opening-auction edge — only 09:15 is "
                         "net-positive after costs; every later bar is negative.")
    ap.add_argument("--require-down-day", action="store_true",
                    help="NIFTY day-type gate: block SHORT unless the NIFTY "
                         "day_type is GAP_DOWN (sets INST_REQUIRE_DOWN_DAY=1). "
                         "Per-trade analysis: GAP_DOWN is the only day_type with "
                         "a net-positive SHORT edge after costs.")
    ap.add_argument("--symbols", default=None,
                    help="Restrict to a subset (comma/space separated)")
    ap.add_argument("--folds", type=int, default=None,
                    help="Rolling walk-forward: N out-of-sample windows "
                         "(requires --train-start and --test-end)")
    ap.add_argument("--shorts", action="store_true",
                    help="Validate SHORT signals out-of-sample (sets "
                         "INST_SHORT_MIN_SCORE=40 so SHORT candidates can clear)")
    ap.add_argument("--min-pf", type=float, default=MIN_PF,
                    help=f"Whitelist PF threshold (default {MIN_PF})")
    ap.add_argument("--min-trades", type=int, default=MIN_TRADES,
                    help=f"Whitelist min trades (default {MIN_TRADES})")
    ap.add_argument("--net-min", type=float, default=0.0,
                    help="Whitelist NET expectancy floor (R/trade, after costs). "
                         "Default 0.0 → only symbols net-profitable on the train "
                         "window are whitelisted. This is what makes the OOS book "
                         "tradeable (gross-PF selection hides cost-eaten symbols).")
    args = ap.parse_args()

    # Set the SHORT acceptance score BEFORE importing the backtest engine, whose
    # module-level SHORT_MIN_PROB constant freezes at import time. Default (no
    # --shorts) keeps SHORT suppressed at 70 so only LONG is validated.
    os.environ["INST_SHORT_MIN_SCORE"] = "40" if args.shorts else "70"

    # Lazy import now that the env var is set.
    global resolve_upstox_key, WalkForwardBacktest
    from scripts.backtest import WalkForwardBacktest, resolve_upstox_key

    intraday = not args.no_intraday
    key = bucket_key(args.timeframe, intraday)
    # Validate only the side we're checking — isolate SHORT (or LONG) stats so
    # the OOS report reflects the validated edge, not the combined book.
    direction = "SHORT" if args.shorts else "LONG"
    key = f"{key}:{direction}"

    # imports for timestamp handling
    global pd_to_ts, pd_Timestamp
    import pandas as pd
    pd_to_ts = lambda s: pd.to_datetime(s)
    pd_Timestamp = pd.Timestamp

    # Resolve symbol subset (strip .NS, allow comma/space).
    if args.symbols:
        symbols = []
        for tok in args.symbols.replace(",", " ").split():
            tok = tok.strip()
            if tok.endswith(".NS"):
                tok = tok[:-3]
            if tok:
                symbols.append(tok)
    else:
        symbols = None

    if args.folds:
        if not (args.train_start and args.test_end):
            print("[ERROR] --folds requires --train-start and --test-end",
                  file=_sys.stderr)
            _sys.exit(2)
        # folds N out-of-sample windows require N+1 segments (N+2 boundaries).
        bnds = _fold_boundaries(args.train_start, args.test_end, args.folds + 1)
        print(f"[walk-forward] {args.timeframe} {args.train_start} -> "
              f"{args.test_end}  ({args.folds} OOS folds)")
        all_wl = []
        for i in range(1, args.folds + 1):
            tr_s, tr_e = bnds[0], bnds[i]
            te_s, te_e = bnds[i], bnds[i + 1]
            print(f"\n=== FOLD {i}: train [{tr_s.date()} -> {tr_e.date()}) "
                  f"| test [{te_s.date()} -> {te_e.date()}) ===")
            wl, test_wl = _run_pair(args.timeframe, intraday, tr_s, tr_e,
                                     te_s, te_e, args.sl, args.tp, symbols, key,
                                     direction, args.min_pf, args.min_trades,
                                     args.short_sl, args.short_tp, args.net_min,
                                     args.short_open_only, args.require_down_day)
            _report_oos(key, test_wl)
            all_wl.extend(test_wl)
        print("\n[AGGREGATE OOS across all folds]")
        _report_oos(f"{key} (all folds)", all_wl)
        return

    # --- original single train/test behaviour ---
    if not (args.train_start and args.train_end and args.test_start
            and args.test_end):
        print("[ERROR] single-pair mode requires --train-start/end and "
              "--test-start/end (or use --folds)", file=_sys.stderr)
        _sys.exit(2)
    if pd_Timestamp(args.test_start) < pd_Timestamp(args.train_end):
        print(
            f"[ERROR] test window ({args.test_start}) starts before train "
            f"window ends ({args.train_end}). Windows overlap — OOS result "
            f"would be invalid. Use --test-start >= --train-end.",
            file=_sys.stderr,
        )
        _sys.exit(2)

    print(f"[train] {args.timeframe} {args.train_start} → {args.train_end}")
    train = _portfolio_stats(args.timeframe, intraday, args.train_start,
                             args.train_end, args.sl, args.tp, symbols, direction,
                             args.short_sl, args.short_tp, args.short_open_only,
                             require_down_day=False)
    wl = _build_whitelist_from(train, args.min_pf, args.min_trades, args.net_min)
    print(f"[train] {len(wl)} symbols passed (PF>={args.min_pf}, trades>={args.min_trades})")

    print(f"[test]  {args.timeframe} {args.test_start} → {args.test_end} (disjoint)")
    test = _portfolio_stats(args.timeframe, intraday, args.test_start,
                            args.test_end, args.sl, args.tp, symbols, direction,
                            args.short_sl, args.short_tp, args.short_open_only,
                            args.require_down_day)
    test_wl = [r for r in test if r["symbol"] in wl]
    _report_oos(key, test_wl)


if __name__ == "__main__":
    main()
