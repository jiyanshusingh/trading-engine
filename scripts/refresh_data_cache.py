"""
Regular data-cache refresher for the full NSE universe — Phase 35.

Fetches TRUE NATIVE candles for every timeframe from Upstox V3
(minutes/1, minutes/15, minutes/30, hours/1, days/1) — no resampling — for all
symbols in ``data/nse_universe.json`` (NIFTY 500 + F&O), and merges them into the
parquet cache (``data/cache/<tf>/<symbol>.parquet``) with dedup.

Modes
-----
  --backfill   One-shot: fetch full history per TF (deep) and merge.
  --eod        Daily top-up: fetch the recent window (incl. today) and merge.
  --loop       Run --eod once per day shortly after market close, then sleep.

Native V3 depths (per request limits handled by the provider's chunker):
  1m  minutes/1   — backfill 60d   (Upstox: 1 month/request, data from 2022)
  15m minutes/15  — backfill 730d  (1 month/request)
  30m minutes/30  — backfill 1095d (1 quarter/request)
  1h  hours/1     — backfill 1095d (1 quarter/request)
  1d  days/1      — backfill 1825d (1 decade/request, single call)

Usage
-----
    .venv/bin/python scripts/refresh_data_cache.py --backfill
    .venv/bin/python scripts/refresh_data_cache.py --backfill --tf 1d 1h --symbols RELIANCE TCS
    .venv/bin/python scripts/refresh_data_cache.py --eod
    .venv/bin/python scripts/refresh_data_cache.py --loop
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, ".")

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
_log = logging.getLogger("refresh_cache")

_CACHE_DIR = Path("data/cache")
_UNIVERSE_PATH = Path("data/nse_universe.json")
_COLS = ["timestamp", "open", "high", "low", "close", "volume"]

# tf -> backfill lookback (days). EOD always uses a short top-up window.
# Priority order (1d/15m first) so the most useful data lands first and an
# interrupted backfill still leaves every symbol with its critical timeframes.
_BACKFILL_DAYS = {"1d": 1825, "15m": 730, "30m": 730, "1h": 730, "1m": 45}
_EOD_DAYS = {"1d": 10, "15m": 10, "30m": 20, "1h": 20, "1m": 5}
_TF_PRIORITY = ["1d", "15m", "30m", "1h", "1m"]
_ALL_TFS = _TF_PRIORITY

_write_lock = threading.Lock()


def _load_universe() -> dict[str, str]:
    if not _UNIVERSE_PATH.exists():
        _log.error("%s not found — run scripts/build_nse_universe.py first", _UNIVERSE_PATH)
        sys.exit(1)
    d = json.loads(_UNIVERSE_PATH.read_text())
    return d["keys"]


def _merge_write(new_df: pd.DataFrame, symbol: str, tf: str) -> int:
    """Merge new bars into the cache parquet (dedup on timestamp, keep last)."""
    path = _CACHE_DIR / tf / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    new_df = new_df[_COLS].copy()
    new_df["timestamp"] = pd.to_datetime(new_df["timestamp"], utc=True).dt.tz_convert(
        "Asia/Kolkata").dt.tz_localize(None)
    with _write_lock:
        if path.exists():
            try:
                old = pd.read_parquet(path)
                old["timestamp"] = pd.to_datetime(old["timestamp"])
                if old["timestamp"].dt.tz is not None:
                    old["timestamp"] = old["timestamp"].dt.tz_localize(None)
                new_df = pd.concat([old[_COLS], new_df], ignore_index=True)
            except Exception as e:
                _log.debug("  %s %s: could not merge old cache (%s) — overwriting", symbol, tf, e)
        merged = (new_df.dropna(subset=["open", "high", "low", "close"])
                  .drop_duplicates(subset=["timestamp"], keep="last")
                  .sort_values("timestamp").reset_index(drop=True))
        merged["volume"] = pd.to_numeric(merged["volume"], errors="coerce").fillna(0).astype("int64")
        merged.to_parquet(path, index=False)
    return len(merged)


def _cache_is_current(symbol: str, tf: str, max_stale_days: int = 4) -> bool:
    """True if the cache for (symbol, tf) already has a bar within the last
    ``max_stale_days`` calendar days (covers weekends/holidays) — used to make
    --backfill resumable and to skip symbols already topped up by EOD."""
    path = _CACHE_DIR / tf / f"{symbol}.parquet"
    if not path.exists():
        return False
    try:
        ts = pd.read_parquet(path, columns=["timestamp"])["timestamp"]
        last = pd.to_datetime(ts).max()
        if getattr(last, "tzinfo", None) is not None:
            last = last.tz_localize(None)
        return (datetime.now() - last.to_pydatetime()).days <= max_stale_days
    except Exception:
        return False


def _fetch_tf(provider, key: str, tf: str, days: int, include_today: bool) -> pd.DataFrame:
    """Fetch native V3 history for one (symbol, tf) with light retry."""
    end = datetime.now()
    start = end - timedelta(days=days)
    frames = []
    for attempt in range(3):
        try:
            hist = provider.load_historical_v3(key, tf, start, end)
            if hist is not None and not hist.empty:
                frames.append(hist)
            break
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            _log.debug("  %s %s hist err: %s", key, tf, e)
            break
    if include_today:
        try:
            intra = provider.load_intraday_v3(key, tf)
            if intra is not None and not intra.empty:
                frames.append(intra)
        except Exception as e:
            _log.debug("  %s %s intraday err: %s", key, tf, e)
    if not frames:
        return pd.DataFrame(columns=_COLS)
    return pd.concat(frames, ignore_index=True)


def _process_one(provider, symbol: str, key: str, tf: str,
                 days: int, include_today: bool) -> int:
    df = _fetch_tf(provider, key, tf, days, include_today)
    if df is None or df.empty:
        return 0
    return _merge_write(df, symbol, tf)


def run(mode: str, tfs: list[str], symbols: dict[str, str], workers: int,
        resume: bool = False) -> None:
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_market_data_provider import UpstoxMarketDataProvider

    token = UPSTOX.get("access_token", "")
    if not token:
        _log.error("No Upstox token in .env — cannot fetch data")
        sys.exit(1)
    provider = UpstoxMarketDataProvider(token)

    lookback = _BACKFILL_DAYS if mode == "backfill" else _EOD_DAYS
    include_today = True  # always grab today's bars so the cache is fully current
    # Process in TF-priority order (1d, 15m, …) so critical data lands first.
    ordered_tfs = [tf for tf in _TF_PRIORITY if tf in tfs]

    t0 = time.time()
    _log.info("=== %s: %d symbols × %s (workers=%d, resume=%s) ===",
              mode.upper(), len(symbols), ",".join(ordered_tfs), workers, resume)
    grand_fail = 0
    for tf in ordered_tfs:
        pending = {s: k for s, k in symbols.items()
                   if not (resume and _cache_is_current(s, tf))}
        skipped = len(symbols) - len(pending)
        if not pending:
            _log.info("  %s: all %d symbols already current — skipped", tf, skipped)
            continue
        tf_t0 = time.time()
        done = fails = total = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_process_one, provider, s, k, tf, lookback[tf], include_today): s
                    for s, k in pending.items()}
            for fut in as_completed(futs):
                sym = futs[fut]
                done += 1
                try:
                    total += fut.result()
                except Exception as e:
                    fails += 1
                    _log.warning("  %s %s FAILED: %s", sym, tf, e)
                if done % 50 == 0 or done == len(pending):
                    _log.info("  %s [%d/%d] (skip %d) — %s bars, %.0fs elapsed",
                              tf, done, len(pending), skipped, f"{total:,}", time.time() - tf_t0)
        grand_fail += fails
        _log.info("  %s DONE: %d fetched, %d skipped, %d failed, %s bars, %.0fs",
                  tf, done - fails, skipped, fails, f"{total:,}", time.time() - tf_t0)
    _log.info("=== %s complete in %.0fs (%.1f min), %d failures ===",
              mode.upper(), time.time() - t0, (time.time() - t0) / 60, grand_fail)


def _loop(tfs: list[str], symbols: dict[str, str], workers: int) -> None:
    """Run EOD once per trading day, ~30 min after market close (16:00 IST)."""
    _log.info("Loop mode: will run EOD refresh daily after market close (16:00 IST).")
    last_run_date = None
    while True:
        now = datetime.now()
        # Run once per day at/after 16:00 IST on a day the market was open.
        if now.hour >= 16 and last_run_date != now.date():
            try:
                run("eod", tfs, symbols, workers)
                last_run_date = now.date()
            except Exception as e:
                _log.error("EOD run failed: %s", e)
        time.sleep(300)  # check every 5 min


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh the NSE-universe data cache (Upstox V3 native)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--backfill", action="store_true", help="One-shot deep history fetch")
    g.add_argument("--eod", action="store_true", help="Daily top-up (recent window incl. today)")
    g.add_argument("--loop", action="store_true", help="Run EOD daily after market close")
    ap.add_argument("--tf", nargs="*", default=_ALL_TFS, help="Timeframes (default: all 5)")
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="Restrict to specific symbols (default: full universe)")
    ap.add_argument("--workers", type=int, default=8, help="Parallel fetch workers (default 8)")
    ap.add_argument("--resume", action="store_true",
                    help="Skip (symbol, tf) already current in cache (resume an interrupted backfill)")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch everything even if the cache looks current (overrides --resume)")
    args = ap.parse_args()

    tfs = [t for t in args.tf if t in _ALL_TFS]
    if not tfs:
        _log.error("No valid timeframes in %s (valid: %s)", args.tf, _ALL_TFS)
        sys.exit(1)

    universe = _load_universe()
    if args.symbols:
        want = set(args.symbols)
        universe = {s: k for s, k in universe.items() if s in want}
        missing = want - set(universe)
        if missing:
            _log.warning("Not in universe (skipped): %s", ", ".join(sorted(missing)))
    if not universe:
        _log.error("No symbols to process"); sys.exit(1)

    if args.loop:
        _loop(tfs, universe, args.workers)
    elif args.backfill:
        run("backfill", tfs, universe, args.workers, resume=(args.resume and not args.force))
    else:  # default / --eod
        run("eod", tfs, universe, args.workers, resume=(args.resume and not args.force))


if __name__ == "__main__":
    main()
