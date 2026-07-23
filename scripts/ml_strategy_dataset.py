"""
Phase B1 — ML Standalone Strategy: bar-level labeled dataset generator.

Unlike Phase 30 (which FILTERED existing strategy signals), this builds a dataset
to train a model that GENERATES entries from raw market state. For every Nth bar
of every symbol we:

  1. compute a self-contained feature vector (stock OHLCV technicals + 30m/1d
     context + NIFTY context + time-of-day), strictly point-in-time (no lookahead
     for features — only data up to and including the entry bar), and
  2. LABEL it by simulating a LONG entry forward with fixed SL/TP and a max hold,
     using the SAME cost model + position sizing as the backtest, so the label is
     `pnl_net > 0` (net-positive after costs) — the exact target from Phase 30.

The feature formulas mirror `WalkForwardBacktest._compute_entry_features` and
`build_htf_context` in scripts/backtest.py, but are VECTORISED per symbol (the
static method recomputes rolling stats over the whole prefix each call, which is
O(n^2) when called ~1M times).

Output: data/ml_strategy_dataset.parquet

Config (chosen with the user, Phase B):
  SL 0.5% / TP 5.0% (intraday, like Manual) · max hold 96 bars (24h @ 15m)
  sample every 3rd bar · skip ambiguous bars (SL & TP both hit in the same bar)
  LONG only · costs = backtest default · 155 symbols with 15m+1d cache

Usage:
  .venv/bin/python scripts/ml_strategy_dataset.py            # all symbols
  .venv/bin/python scripts/ml_strategy_dataset.py --symbols WIPRO,ONGC --limit 5
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.downloader.data_registry import get_bars  # noqa: E402
from scripts.backtest import _resample_1m_to  # noqa: E402
from scripts.capital_model import position_size_for  # noqa: E402

# ── Config ─────────────────────────────────────────────────────────
SL_PCT = 0.005          # 0.5% stop loss (fraction)
TP_PCT = 0.05           # 5.0% take profit (fraction)
MAX_HOLD = 96           # bars (24h @ 15m)
SAMPLE_EVERY = 3        # use every Nth bar
WARMUP = 80             # bars needed before an entry (EMA50 + buffer)
DIRECTION = "LONG"
OUT_PATH = "data/ml_strategy_dataset.parquet"

# Cost model (mirror scripts/backtest.py defaults)
SLIPPAGE_PCT = float(os.environ.get("INST_SLIPPAGE_PCT", "0.05"))
BROKERAGE = float(os.environ.get("INST_BROKERAGE", "20.0"))
STT_PCT = float(os.environ.get("INST_STT_PCT", "0.025"))
GST_PCT = float(os.environ.get("INST_GST_PCT", "18.0"))
EXCHANGE_FEE_PCT = float(os.environ.get("INST_EXCHANGE_FEE_PCT", "0.0001"))


def _trade_cost(entry: float, exit_px: float, notional: float) -> float:
    """Round-trip cost in ₹ (LONG). Mirrors WalkForwardBacktest._compute_costs."""
    slippage = notional * (SLIPPAGE_PCT / 100.0) * 2
    brokerage = BROKERAGE
    stt = exit_px * (notional / entry) * (STT_PCT / 100.0) if entry > 0 else 0.0
    exchange = (notional * 2) * (EXCHANGE_FEE_PCT / 100.0)
    gst = (brokerage + exchange) * (GST_PCT / 100.0)
    return slippage + brokerage + stt + exchange + gst


# ── Vectorised feature computation (mirrors _compute_entry_features) ─
def _rsi_series(close: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI(14) per bar, aligned so out[i] == _rsi(close[:i+1])."""
    delta = np.diff(close)                       # len N-1
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    ag = pd.Series(gain).rolling(period, min_periods=period).mean().values
    al = pd.Series(loss).rolling(period, min_periods=period).mean().values
    rs = ag / np.where(al == 0, 1e-10, al)
    rsi_on_delta = 100.0 - (100.0 / (1.0 + rs))  # len N-1, index d = close[d+1]-close[d]
    out = np.full(len(close), np.nan)
    out[1:] = rsi_on_delta                        # bar i uses delta ending at i => rsi_on_delta[i-1]
    return out


def _atr_series(high, low, close, period: int = 14) -> np.ndarray:
    """ATR(14) per bar, aligned so out[i] == _atr(high[:i+1],...)."""
    tr = np.empty(len(close))
    tr[0] = high[0] - low[0]
    tr[1:] = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - close[:-1]),
        np.abs(low[1:] - close[:-1]),
    ])
    return pd.Series(tr).rolling(period).mean().values


def compute_stock_features(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised per-bar features matching _compute_entry_features."""
    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    vol = (df["volume"].values.astype(float) if "volume" in df.columns
           else np.ones(len(df)))
    n = len(df)
    c = pd.Series(close)

    rsi = _rsi_series(close)
    atr = _atr_series(high, low, close)
    atr_pct = atr / np.maximum(close, 0.01) * 100.0

    # volume_ratio: vol[i] / mean(vol[i-20..i-1])
    avg_vol = pd.Series(vol).rolling(20).mean().shift(1).values
    vol_ratio = vol / np.where((avg_vol == 0) | np.isnan(avg_vol), 1e-10, avg_vol)

    bb_mid = c.rolling(20).mean().values
    bb_std = c.rolling(20).std().values           # ddof=1, matches pandas .std()
    bb_width = np.where(bb_mid > 0, (bb_std * 4.0) / np.maximum(bb_mid, 0.01) * 100.0, 0.0)

    roll_high = c.rolling(20).max().values
    roll_low = pd.Series(low).rolling(20).min().values
    roll_high_h = pd.Series(high).rolling(20).max().values
    recent_high_dist = (roll_high_h - close) / np.maximum(close, 0.01) * 100.0
    recent_low_dist = (close - roll_low) / np.maximum(close, 0.01) * 100.0

    ema20 = c.ewm(span=20, adjust=False).mean().values
    ema50 = c.ewm(span=50, adjust=False).mean().values
    ema20_dist = (close - ema20) / np.maximum(close, 0.01) * 100.0
    ema50_dist = (close - ema50) / np.maximum(close, 0.01) * 100.0

    _ = roll_high  # (roll_high on close unused; high-based used above)
    return pd.DataFrame({
        "timestamp": df["timestamp"].values,
        "close": close, "high": high, "low": low,
        "rsi_14": rsi, "atr_pct": atr_pct, "volume_ratio": vol_ratio,
        "bb_width": bb_width, "recent_high_dist_pct": recent_high_dist,
        "recent_low_dist_pct": recent_low_dist,
        "ema20_dist_pct": ema20_dist, "ema50_dist_pct": ema50_dist,
    })


def compute_30m_context(df15: pd.DataFrame) -> pd.DataFrame:
    """Per-30m-bar context: 30m_return_3, 30m_atr, 30m_trend (window of 5 bars)."""
    df30 = _resample_1m_to(df15, 30)
    if df30 is None or df30.empty or len(df30) < 5:
        return pd.DataFrame(columns=["timestamp", "30m_return_3", "30m_atr", "30m_trend"])
    close = df30["close"].values.astype(float)
    ret3 = np.full(len(df30), np.nan)
    ret3[4:] = (close[4:] - close[:-4]) / close[:-4] * 100.0
    atr = (df30["high"].astype(float) - df30["low"].astype(float)).rolling(5).mean().values
    trend = np.where(ret3 > 0.5, "UP", np.where(ret3 < -0.5, "DOWN", "FLAT"))
    return pd.DataFrame({
        "timestamp": df30["timestamp"].values,
        "30m_return_3": np.round(ret3, 2),
        "30m_atr": np.round(atr, 2),
        "30m_trend": trend,
    })


def compute_1d_context(df1d: pd.DataFrame) -> pd.DataFrame:
    """Per-daily-bar context: 1d_return, 1d_trend (return of that completed day)."""
    if df1d is None or df1d.empty or len(df1d) < 2:
        return pd.DataFrame(columns=["date", "1d_return", "1d_trend"])
    d = df1d.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    close = d["close"].values.astype(float)
    ret = np.full(len(d), np.nan)
    ret[1:] = (close[1:] - close[:-1]) / close[:-1] * 100.0
    trend = np.where(ret > 0.5, "UP", np.where(ret < -0.5, "DOWN", "FLAT"))
    return pd.DataFrame({
        "date": d["timestamp"].dt.date.values,
        "1d_return": np.round(ret, 2),
        "1d_trend": trend,
    })


def _merge_asof_backward(base: pd.DataFrame, ctx: pd.DataFrame, on="timestamp",
                         exact=True) -> pd.DataFrame:
    if ctx is None or ctx.empty:
        return base
    base = base.sort_values(on).reset_index(drop=True)
    ctx = ctx.sort_values(on).reset_index(drop=True)
    base[on] = pd.to_datetime(base[on])
    ctx[on] = pd.to_datetime(ctx[on])
    return pd.merge_asof(base, ctx, on=on, direction="backward",
                         allow_exact_matches=exact)


def label_forward(feat: pd.DataFrame, direction: str) -> pd.DataFrame:
    """Forward-simulate a LONG or SHORT entry with fixed SL/TP for every row;
    attach pnl_net.

    Skips ambiguous bars (SL and TP both first-hit in the same bar) and bars
    without a full forward window / infeasible sizing.
    """
    close = feat["close"].values
    high = feat["high"].values
    low = feat["low"].values
    n = len(feat)
    pnl_net = np.full(n, np.nan)
    is_long = direction == "LONG"

    for i in range(n - 1):
        entry = close[i]
        if entry <= 0:
            continue
        if is_long:
            sl_price = entry * (1.0 - SL_PCT)
            tp_price = entry * (1.0 + TP_PCT)
        else:
            sl_price = entry * (1.0 + SL_PCT)   # stop above for SHORT
            tp_price = entry * (1.0 - TP_PCT)   # target below for SHORT
        end = min(i + 1 + MAX_HOLD, n)
        w_low = low[i + 1:end]
        w_high = high[i + 1:end]
        if len(w_low) == 0:
            continue
        if is_long:
            sl_hits = w_low <= sl_price          # LONG: SL when price drops
            tp_hits = w_high >= tp_price         # LONG: TP when price rises
        else:
            sl_hits = w_high >= sl_price         # SHORT: SL when price rises
            tp_hits = w_low <= tp_price          # SHORT: TP when price drops
        sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else -1
        tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else -1

        if sl_idx >= 0 and tp_idx >= 0 and sl_idx == tp_idx:
            continue  # ambiguous: both first hit in the same bar
        if sl_idx >= 0 and (tp_idx < 0 or sl_idx < tp_idx):
            exit_px = sl_price
        elif tp_idx >= 0 and (sl_idx < 0 or tp_idx < sl_idx):
            exit_px = tp_price
        else:
            exit_px = close[end - 1]      # max hold: exit at last bar close

        notional = position_size_for(entry, sl_price)
        if notional <= 0:
            continue
        shares = notional / entry
        gross = shares * (exit_px - entry) if is_long else shares * (entry - exit_px)
        cost = _trade_cost(entry, exit_px, notional)
        pnl_net[i] = gross - cost

    feat = feat.copy()
    feat["pnl_net"] = pnl_net
    feat["direction"] = direction
    return feat[feat["pnl_net"].notna()].copy()


def process_symbol(symbol: str, nifty30: pd.DataFrame, nifty1d: pd.DataFrame) -> pd.DataFrame | None:
    df15 = get_bars(symbol, "15m", 100000, live=False)
    if df15 is None or len(df15) < WARMUP + MAX_HOLD + 50:
        return None
    df15 = df15.sort_values("timestamp").reset_index(drop=True)
    df1d = get_bars(symbol, "1d", 100000, live=False)

    feat = compute_stock_features(df15)
    # stock 30m + 1d context
    feat = _merge_asof_backward(feat, compute_30m_context(df15))
    d1 = compute_1d_context(df1d)
    feat["date"] = pd.to_datetime(feat["timestamp"]).dt.date
    if not d1.empty:
        # 1d context uses strictly-prior completed day → shift by mapping date<D.
        d1s = d1.copy()
        d1s["date"] = pd.to_datetime(d1s["date"])
        feat_dates = pd.to_datetime(feat["date"])
        tmp = pd.merge_asof(
            pd.DataFrame({"date": feat_dates}).sort_values("date").reset_index(),
            d1s.sort_values("date"),
            on="date", direction="backward", allow_exact_matches=False,
        ).set_index("index").sort_index()
        feat["1d_return"] = tmp["1d_return"].values
        feat["1d_trend"] = tmp["1d_trend"].values
    else:
        feat["1d_return"] = np.nan
        feat["1d_trend"] = "FLAT"

    # NIFTY context (market regime)
    feat = _merge_asof_backward(feat, nifty30.rename(columns={
        "30m_return_3": "nifty_30m_return_3", "30m_atr": "nifty_30m_atr",
        "30m_trend": "nifty_30m_trend"}))
    nd = nifty1d.rename(columns={"1d_return": "nifty_1d_return", "1d_trend": "nifty_1d_trend"})
    if not nd.empty:
        nds = nd.copy(); nds["date"] = pd.to_datetime(nds["date"])
        feat_dates = pd.to_datetime(feat["date"])
        tmp = pd.merge_asof(
            pd.DataFrame({"date": feat_dates}).sort_values("date").reset_index(),
            nds.sort_values("date"),
            on="date", direction="backward", allow_exact_matches=False,
        ).set_index("index").sort_index()
        feat["nifty_1d_return"] = tmp["nifty_1d_return"].values
        feat["nifty_1d_trend"] = tmp["nifty_1d_trend"].values

    # time features
    ts = pd.to_datetime(feat["timestamp"])
    feat["hour"] = ts.dt.hour + ts.dt.minute / 60.0
    feat["weekday"] = ts.dt.weekday

    # warmup + sampling: drop first WARMUP bars, keep every SAMPLE_EVERY-th
    feat = feat.iloc[WARMUP:].reset_index(drop=True)
    feat = feat.iloc[::SAMPLE_EVERY].reset_index(drop=True)
    # drop rows with missing core features
    core = ["rsi_14", "atr_pct", "bb_width", "ema50_dist_pct"]
    feat = feat.dropna(subset=core).reset_index(drop=True)
    if feat.empty:
        return None

    parts = []
    for d in ("LONG", "SHORT"):
        lab = label_forward(feat, d)
        if not lab.empty:
            parts.append(lab)
    if not parts:
        return None
    labeled = pd.concat(parts, ignore_index=True)
    labeled["symbol"] = symbol
    return labeled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=str, default="", help="comma list; default=all with 15m+1d")
    ap.add_argument("--limit", type=int, default=0, help="limit #symbols (debug)")
    ap.add_argument("--out", type=str, default=OUT_PATH)
    args = ap.parse_args()

    cache15 = set(f[:-8] for f in os.listdir("data/cache/15m") if f.endswith(".parquet"))
    cache1d = set(f[:-8] for f in os.listdir("data/cache/1d") if f.endswith(".parquet"))
    universe = sorted(cache15 & cache1d)
    for idx in ("^NSEI", "^NSEBANK"):
        if idx in universe:
            universe.remove(idx)
    if args.symbols:
        want = [s.strip() for s in args.symbols.split(",") if s.strip()]
        universe = [s for s in universe if s in want]
    if args.limit:
        universe = universe[:args.limit]

    print(f"Universe: {len(universe)} symbols")
    # NIFTY context (loaded once)
    nifty15 = get_bars("^NSEI", "15m", 100000, live=False)
    nifty1d = get_bars("^NSEI", "1d", 100000, live=False)
    nifty30 = (compute_30m_context(nifty15) if nifty15 is not None
               else pd.DataFrame(columns=["timestamp", "30m_return_3", "30m_atr", "30m_trend"]))
    nifty1dc = compute_1d_context(nifty1d) if nifty1d is not None else pd.DataFrame(columns=["date", "1d_return", "1d_trend"])
    print(f"NIFTY context: 30m={len(nifty30)} rows, 1d={len(nifty1dc)} rows")

    frames = []
    t0 = time.time()
    for k, sym in enumerate(universe, 1):
        try:
            out = process_symbol(sym, nifty30, nifty1dc)
        except Exception as e:
            print(f"  [{k}/{len(universe)}] {sym} ERROR: {e}")
            continue
        if out is not None and not out.empty:
            frames.append(out)
            wr = 100.0 * (out["pnl_net"] > 0).mean()
            print(f"  [{k}/{len(universe)}] {sym}: {len(out)} entries, "
                  f"{wr:.1f}% net+ ({time.time()-t0:.0f}s)")
        else:
            print(f"  [{k}/{len(universe)}] {sym}: no data")

    if not frames:
        print("No data generated."); return
    ds = pd.concat(frames, ignore_index=True)
    # drop helper columns not used as features
    ds.drop(columns=["close", "high", "low", "date"], errors="ignore", inplace=True)
    os.makedirs("data", exist_ok=True)
    ds.to_parquet(args.out, index=False)
    print(f"\nSaved {len(ds):,} labeled entries from {len(frames)} symbols -> {args.out}")
    print(f"Overall net-positive rate: {100.0*(ds['pnl_net']>0).mean():.1f}%")
    print(f"Total net PnL (all bars, unfiltered): ₹{ds['pnl_net'].sum():+,.0f}")
    print(f"Elapsed: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
