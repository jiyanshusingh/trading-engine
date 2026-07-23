"""
Slippage + transaction-cost model for the Institutional Probability backtests
and paper trader (Indian equity / F&O intraday).

All functions are PURE arithmetic — no global state, no side effects, no
imports of engine/backtest code. You may import this module from anywhere
without freezing or mutating strategy config.

The model is OPT-IN: it is only applied when the caller passes a cost object
or calls these functions explicitly. Default cost parameters are conservative
estimates for a discount broker (Zerodha-style); override them per your broker.

Realistic per-trade cost breakdown (intraday equity, NSE):
  • STT (Securities Transaction Tax): 0.025% on sell turnover (equity
    intraday). We approximate a round-trip as 0.025% of total turnover.
  • Brokerage: flat ₹20/order (or a % — we use the flat cap, typical today).
  • Exchange + SEBI turnover fee: ~0.0001% of turnover.
  • GST: 18% on (brokerage + exchange fees).
  • Market impact (slippage): a configurable % of price, applied at BOTH entry
    and exit (worst case). Defaults to 0.05% per side for liquid Nifty names.

Usage
-----
  from scripts.slippage_model import TRADE_COST_DEFAULT, simulate_trade_cost

  cost = simulate_trade_cost(
      shares=100, entry=500.0, exit=510.0,
      direction="LONG", cost=TRADE_COST_DEFAULT,
  )
  # cost.total  -> total round-trip cost in ₹
  # cost.net_pnl -> exit_pnl - total cost
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TradeCost:
    """Per-trade cost parameters (all as fractions of turnover unless noted)."""

    stt_pct: float = 0.00025          # Securities Transaction Tax (round-trip)
    brokerage_per_order: float = 20.0  # flat ₹ per order (entry + exit)
    exchange_fee_pct: float = 0.000001  # NSE + SEBI turnover fee
    gst_on_brokerage_pct: float = 0.18  # GST on (brokerage + exchange fees)
    impact_pct: float = 0.0005          # market impact per side (0.05%)


# Conservative default for liquid Nifty-50 / Nifty-100 names on a discount broker
TRADE_COST_DEFAULT = TradeCost()


@dataclass
class CostBreakdown:
    """Itemized cost of a single round-trip trade."""

    stt: float = 0.0
    brokerage: float = 0.0
    exchange_fees: float = 0.0
    gst: float = 0.0
    impact: float = 0.0
    total: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0


def simulate_trade_cost(
    shares: int,
    entry: float,
    exit: float,
    direction: str = "LONG",
    cost: TradeCost = TRADE_COST_DEFAULT,
) -> CostBreakdown:
    """Compute the full round-trip cost of a trade and the net P&L.

    ``direction`` is "LONG" (buy to open, sell to close) or "SHORT" (sell to
    open, buy to close). Costs are symmetric for both directions here; STT
    formally applies only on the sell side, which both directions have exactly
    once (LONG sells to close, SHORT sells to open), so a round-trip STT is the
    same either way.
    """
    if shares <= 0 or entry <= 0 or exit <= 0:
        return CostBreakdown()

    entry_notional = shares * entry
    exit_notional = shares * exit
    turnover = entry_notional + exit_notional

    # STT on the sell leg's notional (one sell per round trip)
    sell_notional = exit_notional if direction == "LONG" else entry_notional
    stt = sell_notional * cost.stt_pct

    # Flat brokerage per order (entry + exit)
    brokerage = cost.brokerage_per_order * 2

    # Exchange + SEBI turnover fee on full turnover
    exchange_fees = turnover * cost.exchange_fee_pct

    # GST on (brokerage + exchange fees)
    gst = (brokerage + exchange_fees) * cost.gst_on_brokerage_pct

    # Market impact: applied at both entry and exit (worst case)
    impact = (entry_notional + exit_notional) * cost.impact_pct

    total = stt + brokerage + exchange_fees + gst + impact

    gross = (exit - entry) * shares if direction == "LONG" \
        else (entry - exit) * shares
    net = gross - total

    return CostBreakdown(
        stt=round(stt, 2),
        brokerage=round(brokerage, 2),
        exchange_fees=round(exchange_fees, 2),
        gst=round(gst, 2),
        impact=round(impact, 2),
        total=round(total, 2),
        gross_pnl=round(gross, 2),
        net_pnl=round(net, 2),
    )


def entry_slippage(price: float, cost: TradeCost = TRADE_COST_DEFAULT) -> float:
    """Worst-case ADDITIONAL cost (₹) paid at entry due to impact alone."""
    return price * cost.impact_pct


def exit_slippage(price: float, cost: TradeCost = TRADE_COST_DEFAULT) -> float:
    """Worst-case ADDITIONAL cost (₹) paid at exit due to impact alone."""
    return price * cost.impact_pct
