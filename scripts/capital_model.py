"""
Shared capital model for the Institutional Probability strategy.

Single source of truth for account size, per-trade risk, daily entry cap, and
position sizing. Used by BOTH the backtest engine and the paper trader so the
risk model can never silently diverge between simulation and live trading.
"""

from __future__ import annotations

INITIAL_CAPITAL = 50000.0    # ₹ account size
RISK_PER_TRADE_PCT = 1.0     # % of capital risked per trade → ₹500 on ₹50k
MAX_RISK_PCT = 1.5           # hard ceiling on per-trade risk (conviction scaling)
MAX_TRADES_PER_DAY = 5       # cap concurrent-day new entries (quality over quantity)
MAX_DRAWDOWN_PCT = 15.0      # equity drawdown that triggers a full trading halt
DD_WARN_PCT = 10.0           # drawdown that triggers 50% risk reduction

# F&O constants
FNO_CAPITAL = 160000.0       # ₹ F&O account size (1 lot NIFTY futures on NRML)
FNO_RISK_PER_TRADE_PCT = 0.5 # % of F&O capital risked per trade → ₹800 on ₹1.6L


def drawdown_risk_scaler(current_equity: float, peak_equity: float) -> float:
    """Return a risk scaler in {0.0, 0.5, 1.0} based on drawdown from peak.

      drawdown < DD_WARN_PCT     → 1.0  (full risk)
      DD_WARN_PCT ≤ dd < MAX_DD  → 0.5  (halve risk after a losing streak)
      dd ≥ MAX_DRAWDOWN_PCT      → 0.0  (halt new entries)

    ``peak_equity`` should be the running max equity seen so far (persisted in
    portfolio state). Pure function — no state, safe to call anywhere.
    """
    if peak_equity is None or peak_equity <= 0 or current_equity is None:
        return 1.0
    dd = (peak_equity - current_equity) / peak_equity * 100.0
    if dd >= MAX_DRAWDOWN_PCT:
        return 0.0
    if dd >= DD_WARN_PCT:
        return 0.5
    return 1.0


def conviction_multiplier(score: float) -> float:
    """Map an Institutional Probability score to a risk multiplier in [0.5, 1.5].

    Data-backed from 4,924 manual strategy trades (grid search over all
    threshold pairs):

      score < 55  → 0.5x  (marginal: avg R +0.20, WR 20.6%)
      55–69       → 1.0x  (baseline: avg R +0.33–0.43, WR 21%)
      70+         → 1.5x  (strong:   avg R +0.61–1.22, WR 23–31%)

    This replaces the old thresholds (75/85) which were found to reduce risk
    on 97% of trades, losing 45.9% of total R. The new thresholds improve
    total R by +36.3%.
    """
    if score >= 70.0:
        return 1.5
    if score >= 55.0:
        return 1.0
    return 0.5


def ml_proba_multiplier(proba: float) -> float:
    """Map ML Standalone prediction probability to a position-sizing multiplier.

    Data-backed by the Phase B walk-forward experiment (4-fold OOS, 359 trades):
      proba 0.75–0.80 → 1.0x  (the bulk band, avg +₹344/tr — was over-sized at 1.5x)
      proba 0.80+    → 1.5x  (higher-quality, avg +₹726/tr — keep current sizing)

    Replaces conviction_multiplier() for ML Standalone trades. The model's score
    is proba*100 (e.g. 0.78 → 78), so conviction_multiplier() maps every ML
    Standalone trade to its 1.5x bucket (score ≥ 70) and loses the per-trade
    proba signal. This function recovers discrimination within the 0.75–0.95
    range. Aggregate net improves +16.5% (+₹24,953 on the +₹151,630 baseline).
    """
    return 1.5 if proba >= 0.80 else 1.0
# Data-backed from each strategy's own backtest trade set. A multiplier of 0.0
# is a HARD SKIP (no trade that day); <1.0 reduces size; >1.0 amplifies. Keyed
# by weekday() (0=Mon … 4=Fri). Days not listed default to 1.0 (neutral).
#
#   RSM (Relative Strength Momentum, 5,410 swing trades):
#     Wed +0.018R (near-zero) → ×0.5 ; Thu −0.117R (negative every session)
#     → ×0.0 SKIP ; Fri +0.081R (best WR 46%) → ×1.05
#   Manual Institutional (22,022 trades, LONG-only):
#     Mon +0.491R (4.8× Tue morning) → ×1.30 ; Wed already skipped in-strategy
#     → ×0.0 ; Fri +0.294R (2nd best) → ×1.10
# Combined Swing carries its own day-aware gate inside the strategy and has no
# separate trade-level day analysis yet → left neutral here.
_STRATEGY_DAY_MULT = {
    "manual":            {0: 1.30, 2: 0.0, 4: 1.10},
    "relative strength": {2: 0.5, 3: 0.0, 4: 1.05},
}


def _strategy_day_multiplier(strategy: str, weekday: int) -> float | None:
    """Return the per-strategy day-of-week multiplier, or None if the strategy
    has no day map (caller should fall back to the generic weekday rules)."""
    if not strategy:
        return None
    sl = strategy.lower()
    for key, day_map in _STRATEGY_DAY_MULT.items():
        if key in sl:
            return day_map.get(weekday, 1.0)
    return None


def calendar_conviction_multiplier(entry_date: "date", direction: str,
                                   strategy: str | None = None) -> float:
    """Risk multiplier based on day-wise edge patterns (Phase B + Phase 23).

    Amplifies (or suppresses/skips) risk on calendar days where the backtest
    showed a systematic edge. Applied on top of the score-based
    ``conviction_multiplier`` (the two are independent).

    When ``strategy`` is given and it has a per-strategy day map
    (``_STRATEGY_DAY_MULT``), those data-backed weekday multipliers are used
    (a 0.0 return is a HARD SKIP for that day). Otherwise the legacy generic
    weekday rules apply:

      SHORT on Tuesday        → ×1.15  (SHORT's best weekday, +0.271R)
      LONG  on Monday/Friday  → ×1.15  (LONG's best weekdays)

    Event-based boosts apply in BOTH cases:
      Monthly expiry (last Thu) → ×1.30
      Pre- or post-holiday      → ×1.25

    Returns a multiplier in [0.0, 2.0]. The caller must still cap at MAX_RISK_PCT.
    A return of 0.0 means "do not trade this day for this strategy".
    """
    if entry_date is None or direction not in ("LONG", "SHORT"):
        return 1.0
    try:
        from data.utils import nse_calendar as nse
    except Exception:
        nse = None

    d = entry_date if hasattr(entry_date, "date") else entry_date
    try:
        d = d.date()
    except Exception:
        pass

    wd = d.weekday()
    mult = 1.0

    day_mult = _strategy_day_multiplier(strategy, wd)
    if day_mult is not None:
        # Per-strategy day map takes precedence over the generic weekday rules.
        if day_mult == 0.0:
            return 0.0  # hard skip — no trade this day for this strategy
        mult *= day_mult
    else:
        # Legacy generic weekday multipliers (no strategy / unmapped strategy).
        if direction == "SHORT" and wd == 1:       # Tuesday
            mult *= 1.15
        if direction == "LONG" and wd == 0:        # Monday
            mult *= 1.15
        if direction == "LONG" and wd == 4:        # Friday
            mult *= 1.15

    if nse is not None:
        if nse.is_monthly_expiry(d):                         # last Thursday
            mult *= 1.30
        if nse.is_pre_holiday(d) or nse.is_post_holiday(d):  # holiday proximal
            mult *= 1.25
    return min(mult, 2.0)


def futures_position_size(entry: float, sl: float,
                          lot_size: int = 65,
                          contract_multiplier: int | None = None,
                          risk_pct: float | None = None,
                          capital: float | None = None) -> int:
    """Position size for futures contracts — rounds to whole lots.

    Risk budget = capital * risk_pct / 100.
    Shares per lot = lot_size (e.g. 65 for NIFTY).
    Lots = floor(risk_budget / (risk_per_share * lot_size)).
    Returns number of LOTS (not shares). Minimum 1 lot.

    For F&O, the contract_multiplier = lot_size (the notional per contract).
    The P&L = lots * lot_size * (exit - entry) for futures.
    """
    cap = capital if capital is not None else FNO_CAPITAL
    pct = risk_pct if risk_pct is not None else FNO_RISK_PER_TRADE_PCT
    pct = min(pct, MAX_RISK_PCT)
    risk_per_share = abs(entry - sl)
    if risk_per_share <= 0 or entry <= 0 or lot_size <= 0:
        return 0
    risk_budget = cap * (pct / 100.0)
    shares_per_lot = lot_size
    lots = int(risk_budget / (risk_per_share * shares_per_lot))
    if lots < 1:
        return 0
    # Cap by available capital / notional
    max_lots = int(cap / (entry * shares_per_lot))
    if max_lots < 1:
        return 0
    return min(lots, max_lots)


def position_size_for(entry: float, sl: float, risk_pct: float | None = None,
                      capital: float | None = None) -> float:
    """Notional position value for a capital-based fixed-% risk trade.

    Risk budget = capital * risk_pct / 100 (e.g. ₹500 on ₹50k @ 1%).
    ``capital`` defaults to ``INITIAL_CAPITAL`` when omitted (single-strategy).

    Shares = int(risk_budget / risk_per_share). Returns the notional
    (shares * entry). Returns 0.0 when the trade is infeasible (risk_per_share
    too wide to afford even 1 share, or the 1-share notional exceeds capital).

    ``risk_pct`` overrides the module-level RISK_PER_TRADE_PCT (used for
    conviction-based sizing); it is clamped to MAX_RISK_PCT.
    """
    cap = capital if capital is not None else INITIAL_CAPITAL
    pct = risk_pct if risk_pct is not None else RISK_PER_TRADE_PCT
    pct = min(pct, MAX_RISK_PCT)
    risk_per_share = abs(entry - sl)
    if risk_per_share <= 0 or entry <= 0:
        return 0.0
    risk_budget = cap * (pct / 100.0)
    shares = int(risk_budget / risk_per_share)
    if shares < 1:
        return 0.0
    notional = shares * entry
    if notional > cap:
        shares = int(cap / entry)
        if shares < 1:
            return 0.0
        notional = shares * entry
    return notional
