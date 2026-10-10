"""All analysis thresholds, weights and scales in one place.

Every value here is a documented, educational rule. None of them is calibrated
against real market outcomes, so they must not be read as predictive.
"""

# --- Technical windows ----------------------------------------------------
SHORT_MA_WINDOW = 20          # trading days
LONG_MA_WINDOW = 50           # trading days
MIN_BARS_REQUIRED = LONG_MA_WINDOW  # fewer bars than this -> technical analysis unavailable

TRADING_DAYS_PER_YEAR = 252

# --- Momentum: score = clamp(period change / MOMENTUM_SCALE, -1, 1) --------
MOMENTUM_SCALE = 0.20         # a +20% period change maps to score +1.0

# --- Trend ----------------------------------------------------------------
# Each part is clamp(gap / TREND_SCALE, -1, 1):
#   gap_1 = SMA20 / SMA50 - 1
#   gap_2 = price / SMA20 - 1
# trend score = (gap_1 + gap_2) / 2
TREND_SCALE = 0.10            # a 10% gap maps to score +/-1.0

# --- Labels ---------------------------------------------------------------
# |score| below LABEL_BAND is labelled neutral.
LABEL_BAND = 0.20

# --- Risk -----------------------------------------------------------------
# risk_score = min(1, 0.6 * volatility / VOLATILITY_REFERENCE
#                     + 0.4 * max_drawdown / DRAWDOWN_REFERENCE)
RISK_VOLATILITY_WEIGHT = 0.6
RISK_DRAWDOWN_WEIGHT = 0.4
VOLATILITY_REFERENCE = 0.60   # annualized volatility at which the volatility term reaches 1.0
DRAWDOWN_REFERENCE = 0.50     # max drawdown magnitude at which the drawdown term reaches 1.0
RISK_LOW_MAX = 0.33           # risk_score < 0.33 -> low
RISK_MODERATE_MAX = 0.66      # risk_score < 0.66 -> moderate; otherwise high
# Signal passed to the aggregator: 1 - 2 * risk_score (low risk = favorable).

# --- Fundamentals: each available metric maps linearly to [-1, 1] ---------
# value at BAD -> -1.0, value at GOOD -> +1.0, clamped. The fundamental score
# is the mean of the available metric scores.
REVENUE_GROWTH_BAD = 0.00
REVENUE_GROWTH_GOOD = 0.10
PROFIT_MARGIN_BAD = 0.05
PROFIT_MARGIN_GOOD = 0.20
PE_RATIO_BAD = 45.0           # expensive
PE_RATIO_GOOD = 25.0          # cheaper (reversed scale)
EARNINGS_GROWTH_BAD = 0.00
EARNINGS_GROWTH_GOOD = 0.10

# --- Aggregation ----------------------------------------------------------
# Weights apply to component scores. When a component is unavailable its
# weight is removed and the rest are renormalized; it is never counted as 0.
WEIGHTS: dict[str, float] = {
    "momentum": 0.30,
    "trend": 0.30,
    "risk": 0.20,
    "fundamental": 0.20,
}
BUY_THRESHOLD = 0.25          # composite >= 0.25 -> BUY
SELL_THRESHOLD = -0.25        # composite <= -0.25 -> SELL; otherwise HOLD
