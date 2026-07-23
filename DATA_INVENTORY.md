# Data Inventory

Verified 2026-07-13 by direct inspection of `data/cache/**` (parquet row counts)
and the downloader source. This supersedes the stale cache-range numbers in
AGENTS.md (Phase 0 / Phase 5 / Phase 13 sections).

## 1. Parquet cache (`data/cache/`)

| TF  | Files | Bars (approx)      | Date range                | Source / notes                                  |
|-----|-------|--------------------|---------------------------|-------------------------------------------------|
| 15m | 191   | ~2,348,920         | 2024-07-15 → 2026-07-10   | Upstox 1m → 15m resample, 729d. Native 15m unavailable on Upstox (maps to `30minute`). |
| 30m | 30    | ~8,670             | 2026-06-09 → 2026-07-08   | Thin — ~1 month only.                           |
| 1m  | 30    | ~232,410           | 2026-06-09 → 2026-07-08   | Thin — ~1 month only. Upstox caps 1m history at ~30d/request. |
| 1h  | 111   | ~483,058           | 2023-07-28 → 2026-07-13   | Upstox native 1h (`30minute`), ~3yr.            |
| 1d  | 112   | ~137,856           | 2021-07-12 → 2026-07-10   | ~5 years. Deepest TF.                           |
| 5m  | —     | —                  | —                         | No cache directory exists.                      |

Other caches:
- `data/cache_yf/15m/` — 183 files, yfinance-sourced 15m (60-day cap). Overlaps
  `data/cache/15m/` but shallower.
- `data/cache_wf/` (141) / `data/cache_wf_test/` (2) — walk-forward scratch
  caches (override_cache_dir redirects).
- `data/upstox/` (9) — instrument keys + contracts.
- `data/contracts/`, `data/csv/`, `data/csvs/`, `data/normalization/` — ancillary.

## 2. Two downloaders (not one)

- `scripts/download_history.py` — **bulk** historical loader. Flags
  `--tf`, `--symbols`, `--upstox`. yfinance path caps 15m@60d, 1h@730d, 1d@5y;
  `--upstox` unlocks 729d of 15m by resampling 1m (chunked 28d fetches).
- `data/downloader/nse_data_downloader.py` — **incremental** refresh. Pulls only
  newer bars for existing cache. Upstox caps: `{"1minute":30, "30minute":60,
  "day":730}` days/request. Builds 15m/30m from 1m via `candle_aggregator`.

Both exist and are referenced correctly in AGENTS.md command blocks — the
command references are NOT stale. Only the *cache-range numbers* in the prose
are out of date (see §4).

## 3. Live / deployment state files

- `paper_portfolio.json` — **two live strategies allocated**: `Institutional
  Probability` (₹35,000) + `Relative Strength Momentum` (₹15,000). Each carries
  its own `cash` / `positions` / `peak_equity`.
- `live_institutional_scan.json` — Institutional Probability stream.
- `live_scan.json` — older agentic scanner → Price Action + VWAP Pullback buys.
- `trade_history.json` — today's (2026-07-13) Institutional Probability signals.

## 4. Known data-collection problems

1. **Upstox history caps** (hard-coded): 1m = 30d, 30m = 60d, day = 730d per
   request. 1m/30m therefore never accumulate beyond ~1 month; every refresh
   re-fetches the same window.
2. **15m is resampled, never native.** Upstox has no 15m interval (→ `30minute`).
   The resample breaks LONG signal generation on 15m (LONG needs native bar
   structure; SHORT tolerates resampled bars). This is why LONG 15m was never
   OOS-validated.
3. **Silent symbol skips.** `download_history._fetch_upstox` wraps each 28d chunk
   in try/except and logs+skips on failure — a single bad chunk drops that
   symbol's coverage for the window with no hard error. Delisted names
   (ADANITRANS) and DNS blips (ZENTEC: `api.upstox.com` failed to resolve) are
   dropped the same way.
4. **yfinance ticker mis-format.** `^NSEI` / `^NSEBANK` index fetches get a
   `.NS` suffix appended (`^NSEI.NS`) → HTTP 404 "possibly delisted", and the
   backtest then silently runs with **no NIFTY/BANKNIFTY daily/index context**.
   (`data/results/short_oos_*.log` shows `Cache miss (cache-only): ^NSEI @ 1d`.)
   Fixed this session by caching `data/cache/1h/^NSEI.parquet` +
   `^NSEBANK.parquet` manually, but the fetcher still mis-formats and 404s.
5. **Duplicate stacks.** `data/cache/` (Upstox), `data/cache_yf/` (yfinance),
   `data/cache_wf/` (walk-forward) are not guaranteed consistent — e.g. 15m
   exists in both `cache` (729d) and `cache_yf` (60d).
6. **AGENTS.md drift** — the prose cache ranges (15m→60d, 1h→2yr) predate the
   Phase 13 729d backfill and no longer match disk. The "1h Native Data (yfinance)"
   note in AGENTS.md also overstates `data_registry.py`: it resamples 30m→1h,
   it does not fetch native 1h from yfinance.
