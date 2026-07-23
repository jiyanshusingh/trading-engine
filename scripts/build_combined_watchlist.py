"""
Build the `combined_swing` watchlist from the Combined Swing swing backtest.

Filters symbols with PF >= 1.3 AND trades >= 10 from
data/backtest_portfolio_15m_combined_swing.json, then writes:
  - the `combined_swing` list (sorted by PF desc) into data/symbol_watchlists.json
  - a `combined_swing` detail block per symbol in the `details` section

Preserves all other watchlist keys / details.
"""

import json

BACKTEST = "data/backtest_portfolio_15m_combined_swing.json"
WATCHLISTS = "data/symbol_watchlists.json"
MIN_PF = 1.3
MIN_TRADES = 10


def main():
    with open(BACKTEST) as f:
        results = json.load(f)

    # Backtest files vary in shape: a list of per-symbol dicts, or a dict
    # keyed by symbol. Normalize to a per-symbol result map.
    if isinstance(results, dict):
        # some backtest writers nest under "results" / "symbols"
        results = results.get("results", results.get("symbols", results))

    profitable = []
    for r in results:
        sym = r.get("symbol")
        pf = r.get("profit_factor", r.get("pf", 0)) or 0
        tr = r.get("trades", 0) or 0
        if sym and tr >= MIN_TRADES and pf >= MIN_PF:
            profitable.append(r)

    profitable.sort(key=lambda r: (-(r.get("profit_factor", 0) or 0), -(r.get("trades", 0) or 0)))
    symbols = [r["symbol"] for r in profitable]
    print(f"Filtered {len(symbols)} profitable symbols (PF>= {MIN_PF}, trades>= {MIN_TRADES})")

    with open(WATCHLISTS) as f:
        wl = json.load(f)

    wl["combined_swing"] = symbols

    details = wl.setdefault("details", {})
    for r in profitable:
        sym = r["symbol"]
        entry = details.setdefault(sym, {})
        entry["combined_swing"] = {
            "pf": round(r.get("profit_factor", 0) or 0, 2),
            "trades": int(r.get("trades", 0) or 0),
            "avg_r": round(r.get("avg_r", 0) or 0, 3),
            "wr": round(r.get("win_rate", 0) or 0, 1),
            "pnl_pct": round(r.get("total_pnl_pct", 0) or 0, 2),
            "max_dd": round(r.get("max_drawdown", 0) or 0, 2),
        }

    with open(WATCHLISTS, "w") as f:
        json.dump(wl, f, indent=2)

    print(f"Wrote 'combined_swing' watchlist ({len(symbols)} symbols) to {WATCHLISTS}")
    print(f"Top 10: {symbols[:10]}")


if __name__ == "__main__":
    main()
