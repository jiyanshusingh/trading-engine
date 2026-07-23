"""
Opening-minutes ML dataset generator (Phase C1).

For every 5m bar in the opening window (09:15-10:30) across all cached 5m symbols,
build a feature vector from data observable *up to and including* that bar, and
label it by forward-simulating a fixed SL/TP trade.

The label mirrors the existing Phase B5 pipeline (ml_strategy_dataset.py): the
trade is net-positive after costs (pnl_net > 0). Here the timeframe is 5m and the
entry is constrained to the opening hour, with SL/TP chosen for 5m noise.

SL 0.3% / TP 1.5% / max hold 48 bars (4h) · both LONG + SHORT · sample every 2nd bar.

Output: data/ml_orb_dataset.parquet
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.downloader.data_registry import get_bars  # noqa: E402
from scripts.ml_strategy_dataset import (  # reuse Phase B5 helpers
    compute_stock_features, _trade_cost,
)
from scripts.capital_model import position_size_for  # noqa: E402

# ── Config ─────────────────────────────────────────────────────────
SL_PCT = 0.003          # 0.3% stop loss (5m noise is small)
TP_PCT = 0.015          # 1.5% take profit (5:1 R:R)
MAX_HOLD = 48           # bars (4h @ 5m)
SAMPLE_EVERY = 2        # use every Nth opening bar
WARMUP = 80             # bars before first entry (EMA50 + buffer)
OUT_PATH = "data/ml_orb_dataset.parquet"
GAP_THRESHOLD = 0.003

# Cost model (mirror scripts/backtest.py defaults)
SLIPPAGE_PCT = float(os.environ.get("INST_SLIPPAGE_PCT", "0.05"))
BROKERAGE = float(os.environ.get("INST_BROKERAGE", "20.0"))
STT_PCT = float(os.environ.get("INST_STT_PCT", "0.025"))
GST_PCT = float(os.environ.get("INST_GST_PCT", "18.0"))
EXCHANGE_FEE_PCT = float(os.environ.get("INST_EXCHANGE_FEE_PCT", "0.0001"))


def classify_gap(gap_pct, threshold=GAP_THRESHOLD):
    if gap_pct > threshold:
        return "up"
    if gap_pct < -threshold:
        return "down"
    return "flat"


def label_forward_5m(feat: pd.DataFrame, direction: str) -> pd.DataFrame:
    """Forward-simulate a LONG/SHORT trade with fixed SL/TP for every bar."""
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
            sl_price = entry * (1.0 + SL_PCT)
            tp_price = entry * (1.0 - TP_PCT)
        end = min(i + 1 + MAX_HOLD, n)
        w_low = low[i + 1:end]
        w_high = high[i + 1:end]
        if len(w_low) == 0:
            continue
        if is_long:
            sl_hits = w_low <= sl_price
            tp_hits = w_high >= tp_price
        else:
            sl_hits = w_high >= sl_price
            tp_hits = w_low <= tp_price
        sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else -1
        tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else -1
        if sl_idx >= 0 and tp_idx >= 0 and sl_idx == tp_idx:
            continue  # ambiguous: both first hit in the same bar
        if sl_idx >= 0 and (tp_idx < 0 or sl_idx < tp_idx):
            exit_px = sl_price
        elif tp_idx >= 0 and (sl_idx < 0 or tp_idx < sl_idx):
            exit_px = tp_price
        else:
            exit_px = close[end - 1]
        notional = position_size_for(entry, sl_price)
        if notional <= 0:
            continue
        shares = notional / entry
        gross = shares * (exit_px - entry) if is_long else shares * (entry - exit_px)
        cost = _trade_cost(entry, exit_px, notional)
        pnl_net[i] = gross - cost

    out = feat.copy()
    out["pnl_net"] = pnl_net
    out["direction"] = direction
    return out[["timestamp", "pnl_net", "direction"]].dropna(subset=["pnl_net"])


def compute_nifty_context(nifty_df, nifty1d):
    """Return dict: date -> {nifty_1d_return, nifty_1d_trend, nifty_gap_pct}."""
    ctx: dict = {}
    if nifty_df is None or nifty_df.empty:
        return ctx
    nd = nifty_df.copy()
    nd["timestamp"] = pd.to_datetime(nd["timestamp"])
    nd["date"] = nd["timestamp"].dt.date
    days = sorted(nd["date"].unique())
    for i, day in enumerate(days):
        if i == 0:
            continue
        day_bars = nd[nd["date"] == day]
        first_open = day_bars["open"].iloc[0]
        prev_day_bars = nd[nd["date"] == days[i - 1]]
        prev_close = prev_day_bars["close"].iloc[-1] if len(prev_day_bars) else np.nan
        gap = (first_open - prev_close) / prev_close if prev_close > 0 else 0.0
        ctx[day] = {"nifty_gap_pct": gap}

    if nifty1d is not None and not nifty1d.empty:
        n1 = nifty1d.copy()
        n1["timestamp"] = pd.to_datetime(n1["timestamp"])
        n1["date"] = n1["timestamp"].dt.date
        close = n1["close"].values.astype(float)
        ret = np.full(len(n1), np.nan)
        ret[1:] = (close[1:] - close[:-1]) / close[:-1] * 100.0
        trend = np.where(ret > 0.5, "UP", np.where(ret < -0.5, "DOWN", "FLAT"))
        for j, d in enumerate(n1["date"].values):
            if j == 0:
                continue
            ctx[d] = {**ctx.get(d, {}),
                      "nifty_1d_return": ret[j], "nifty_1d_trend": trend[j]}
    return ctx


def add_opening_features(day_df, df5, day, days, idx, nifty_feat_map):
    """Vectorised opening-specific features for one day's bars."""
    day_raw = df5[df5["date"] == day]
    open_range_bars = day_raw[day_raw["time"] <= pd.Timestamp("09:30").time()]
    range_15m = open_range_bars["high"].max() - open_range_bars["low"].min()
    range_30m_bars = day_raw[day_raw["time"] <= pd.Timestamp("09:45").time()]
    range_30m = range_30m_bars["high"].max() - range_30m_bars["low"].min()
    first_bar = day_raw.iloc[0]
    first_open = first_bar["open"]

    prev_day = days[idx - 1]
    prev_day_bars = df5[df5["date"] == prev_day]
    prev_close = prev_day_bars["close"].iloc[-1] if len(prev_day_bars) else np.nan
    gap_pct = (first_open - prev_close) / prev_close if prev_close > 0 else 0.0
    prev_day_high = prev_day_bars["high"].max()
    prev_day_low = prev_day_bars["low"].min()
    prev_day_open = prev_day_bars["open"].iloc[0]
    prev_day_range_pct = ((prev_day_high - prev_day_low) / prev_close
                          if prev_close > 0 else np.nan)
    prev_day_return = ((prev_close - prev_day_open) / prev_day_open
                       if prev_day_open > 0 else np.nan)

    nctx = nifty_feat_map.get(day, {})
    avg_vol = df5["volume"].rolling(20).mean().shift(1)

    out = day_df.copy()
    out["gap_pct"] = gap_pct
    out["gap_dir"] = classify_gap(gap_pct)
    out["opening_range_15m_pct"] = np.where(out["close"] > 0, range_15m / out["close"], np.nan)
    out["opening_range_30m_pct"] = np.where(out["close"] > 0, range_30m / out["close"], np.nan)
    out["price_position_in_range_15m"] = ((out["close"] - open_range_bars["low"].min()) / range_15m
                                          if range_15m > 0 else 0.5)
    out["price_position_in_range_30m"] = ((out["close"] - range_30m_bars["low"].min()) / range_30m
                                          if range_30m > 0 else 0.5)
    out["first_bar_return"] = ((first_bar["close"] - first_bar["open"]) / first_bar["open"]
                               if first_bar["open"] > 0 else 0.0)
    out["first_bar_range_pct"] = ((first_bar["high"] - first_bar["low"]) / first_bar["open"]
                                  if first_bar["open"] > 0 else 0.0)
    fb_avg = avg_vol.loc[first_bar.name] if first_bar.name in avg_vol.index else np.nan
    out["first_bar_volume_ratio"] = (first_bar["volume"] / fb_avg
                                     if (not np.isnan(fb_avg) and fb_avg > 0) else 1.0)
    out["cum_return_since_open"] = ((out["close"] - first_open) / first_open
                                    if first_open > 0 else 0.0)
    out["minutes_since_open"] = ((out["timestamp"].dt.hour - 9) * 60
                                 + (out["timestamp"].dt.minute - 15))
    out["prev_day_range_pct"] = prev_day_range_pct
    out["prev_day_return"] = prev_day_return
    out["nifty_1d_return"] = nctx.get("nifty_1d_return", np.nan)
    out["nifty_1d_trend"] = nctx.get("nifty_1d_trend", "FLAT")
    out["nifty_gap_pct"] = nctx.get("nifty_gap_pct", np.nan)
    out["hour"] = out["timestamp"].dt.hour
    out["minute"] = out["timestamp"].dt.minute
    out["weekday"] = out["timestamp"].dt.weekday
    return out


def process_symbol(symbol, nifty_feat_map):
    df5 = get_bars(symbol, "5m", 100000, live=False)
    if df5 is None or len(df5) < WARMUP + MAX_HOLD + 50:
        return None
    df5 = df5.sort_values("timestamp").reset_index(drop=True)
    df5["timestamp"] = pd.to_datetime(df5["timestamp"])
    df5["date"] = df5["timestamp"].dt.date
    df5["time"] = df5["timestamp"].dt.time

    feat = compute_stock_features(df5)
    feat["date"] = df5["date"].values
    feat["time"] = df5["time"].values
    feat["open"] = df5["open"].values
    feat["volume"] = df5["volume"].values

    lab_l = label_forward_5m(feat, "LONG").set_index("timestamp")["pnl_net"]
    lab_s = label_forward_5m(feat, "SHORT").set_index("timestamp")["pnl_net"]

    days = sorted(df5["date"].unique())
    frames = []
    for idx, day in enumerate(days):
        if idx == 0:
            continue
        day_df = feat[feat["date"] == day]
        if len(day_df) == 0:
            continue
        window_mask = ((day_df["time"] >= pd.Timestamp("09:15").time()) &
                       (day_df["time"] <= pd.Timestamp("10:30").time()))
        if not window_mask.any():
            continue
        enriched = add_opening_features(day_df, df5, day, days, idx, nifty_feat_map)
        enriched = enriched[window_mask].iloc[::SAMPLE_EVERY].copy()
        for direction, lab_map in [("LONG", lab_l), ("SHORT", lab_s)]:
            sub = enriched.copy()
            sub["direction"] = direction
            sub["pnl_net"] = sub["timestamp"].map(lab_map)
            sub = sub.dropna(subset=["pnl_net"])
            if not sub.empty:
                frames.append(sub)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="limit #symbols (debug)")
    ap.add_argument("--out", type=str, default=OUT_PATH)
    args = ap.parse_args()

    files = glob.glob("data/cache/5m/*.parquet")
    symbols = sorted(os.path.basename(f)[:-8] for f in files)
    # Exclude index symbols from the training universe (used only for context)
    symbols = [s for s in symbols if not s.startswith("^")]
    if args.limit:
        symbols = symbols[:args.limit]
    print(f"Universe: {len(symbols)} symbols (5m)")

    nifty_df = get_bars("^NSEI", "5m", 100000, live=False)
    nifty1d = get_bars("^NSEI", "1d", 100000, live=False)
    nifty_feat_map = compute_nifty_context(nifty_df, nifty1d)
    print(f"NIFTY context: {len(nifty_feat_map)} days")

    frames = []
    t0 = time.time()
    for k, sym in enumerate(symbols, 1):
        try:
            out = process_symbol(sym, nifty_feat_map)
        except Exception as e:
            print(f"  [{k}/{len(symbols)}] {sym} ERROR: {e}")
            continue
        if out is not None and not out.empty:
            frames.append(out)
            pos = 100.0 * (out["pnl_net"] > 0).mean()
            print(f"  [{k}/{len(symbols)}] {sym}: {len(out)} rows, "
                  f"{pos:.1f}% net+ ({time.time()-t0:.0f}s)")
        else:
            print(f"  [{k}/{len(symbols)}] {sym}: no data")

    if not frames:
        print("No data generated."); return
    ds = pd.concat(frames, ignore_index=True)
    ds.to_parquet(args.out, index=False)
    print(f"\nSaved {len(ds):,} rows from {len(frames)} symbols -> {args.out}")
    print(f"Overall net+ rate: {100.0*(ds['pnl_net']>0).mean():.1f}%")
    print(f"Total net PnL (unfiltered): ₹{ds['pnl_net'].sum():+,.0f}")
    print(f"Elapsed: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
