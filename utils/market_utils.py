def atr_displacement(
    high,
    low,
    atr
):
    """
    Returns price displacement measured in ATR.
    """

    if atr == 0:
        return 0

    return abs(high - low) / atr

def is_valid_break(close, level, atr, min_atr):
    """
    Returns True if the break is significant.
    """

    if atr <= 0:
        return False

    return close > (level + atr * min_atr)