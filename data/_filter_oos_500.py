import json
import subprocess
import sys

STRATS = {
    "rsm":      ("data/backtest_portfolio_15m_rsm_500.json",
                 "data/backtest_trades_15m_rsm_500.json"),
    "combined": ("data/backtest_portfolio_15m_combined_500.json",
                 "data/backtest_trades_15m_combined_500.json"),
    "manual":   ("data/backtest_portfolio_15m_manual_500.json",
                 "data/backtest_trades_15m_manual_500.json"),
}

MIN_PF = 1.3
MIN_TRADES = 10

for name, (pf_path, tr_path) in STRATS.items():
    pf = json.load(open(pf_path))
    # Symbols profitable at defaults
    profitable = [s for s in pf
                  if s.get("profit_factor", 0) >= MIN_PF
                  and s.get("trades", 0) >= MIN_TRADES]
    profitable.sort(key=lambda s: (-s["profit_factor"], -s["trades"]))
    prof_syms = [s["symbol"] for s in profitable]
    print(f"\n=== {name.upper()} ===")
    print(f"  Total backtested:   {len(pf)}")
    print(f"  Profitable (PF>=1.3, tr>=10): {len(profitable)}")
    net = sum(s.get("total_pnl_pct", 0) for s in profitable)
    print(f"  Sum total_pnl_pct (profitable): {net:+.1f}%")
    # Save profitable list for tuning
    with open(f"data/_500_profitable_{name}.txt", "w") as f:
        f.write(",".join(prof_syms))
    print(f"  Saved data/_500_profitable_{name}.txt ({len(prof_syms)} syms)")
    # Show top 10
    for s in profitable[:10]:
        print(f"    {s['symbol']:14s} tr={s['trades']:4d} PF={s['profit_factor']:.2f} "
              f"WR={s.get('win_rate',0):.1f}% avgR={s.get('avg_r',0):+.2f}")

    # Run OOS both-halves prune on the trades file
    print(f"  Running OOS split-validate on {tr_path} ...")
    subprocess.run([sys.executable, "scripts/oos_split_validate.py", tr_path],
                   check=True)
