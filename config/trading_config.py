# =====================================================
# EMA SETTINGS
# =====================================================

EMA_FAST = 20
EMA_MEDIUM = 50
EMA_SLOW = 200

# =====================================================
# RSI SETTINGS
# =====================================================

RSI_PERIOD = 14
RSI_MIN = 50
RSI_MAX = 70

# =====================================================
# ATR SETTINGS
# =====================================================

ATR_PERIOD = 14

ATR_STOP_MULTIPLIER = 1.5
ATR_TARGET1_MULTIPLIER = 2.0
ATR_TARGET2_MULTIPLIER = 4.0

# =====================================================
# RISK SETTINGS
# =====================================================

MIN_RISK_REWARD = 2.0
MAX_RISK_PER_TRADE = 0.5       # Conservative: 0.5% of capital per trade (user preference)

# =====================================================
# SHORT-SIDE SETTINGS
# =====================================================

SHORT_SL_MULT = 1.0            # Short stop loss = 1.0 * ATR (ensures RR >= 1)
SHORT_TP_MULT = 2.0            # Short take profit = 2.0 * ATR (RR = 2.0)
SHORT_DECISION_THRESHOLD = 50  # Engine bearish score >= 50 triggers SHORT

# =====================================================
# PROBABILITY SETTINGS
# =====================================================

STRONG_BUY_THRESHOLD = 85
BUY_THRESHOLD = 70
WATCH_THRESHOLD = 55

# =====================================================
# TIME-OF-DAY / SESSION SETTINGS
# =====================================================

SESSION_STARTS = {
    "opening": "09:15",
    "morning": "09:45",
    "midday": "11:30",
    "afternoon": "13:30",
    "closing": "15:00",
}

SESSION_ENDS = {
    "opening": "09:45",
    "morning": "11:30",
    "midday": "13:30",
    "afternoon": "15:00",
    "closing": "15:30",
}

# =====================================================
# MARKET STRUCTURE SETTINGS
# =====================================================

# Swing Detection
SWING_LOOKBACK = 5
MIN_SWING_CANDLES = 3
MIN_SWING_ATR = 1.0

# Structure Break Confirmation
STRUCTURE_BREAK_MIN_DISPLACEMENT = 1.0

# ATR Confirmation (Reserved for future versions)
BOS_MIN_ATR = 0.25

# =====================================================
# SCANNER SETTINGS
# =====================================================

TOP_STOCKS = 20

# =====================================================
# BOS QUALITY
# =====================================================

MIN_BODY_PERCENT = 0.60