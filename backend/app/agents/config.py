"""Phase 7 strategy configuration: versions, windows, weights and thresholds.

Every number here is an explicit, educational rule. None is calibrated against real market
outcomes, and none was tuned so that a particular demo symbol gets an attractive result.
Units: returns, growth, margins, volatility and drawdowns are DECIMAL fractions (0.15 = 15%).
P/E is a multiple. Moving averages are in USD.
"""

SCHEMA_VERSION = "agents.v1"

# --- Price windows (trading days, i.e. bars) ---------------------------------------------
RETURN_SHORT_WINDOW = 20      # return_20d = close[t] / close[t-20] - 1   (needs 21 bars)
RETURN_LONG_WINDOW = 60       # return_60d = close[t] / close[t-60] - 1   (needs 61 bars)
SMA_SHORT_WINDOW = 20
SMA_LONG_WINDOW = 50
VOLATILITY_SHORT_WINDOW = 20  # last 20 daily log returns (needs 21 bars)
VOLUME_SHORT_WINDOW = 20
VOLUME_LONG_WINDOW = 60
MIN_BARS_FULL_WINDOW = 21     # volatility_annualized / drawdowns need at least this many bars
TRADING_DAYS_PER_YEAR = 252

# Published metric precision. Rules are evaluated on the PUBLISHED (rounded) values, so every
# cited number can be reproduced from the JSON.
METRIC_DECIMALS = 6

# --- Stance --------------------------------------------------------------------------------
# score = weighted mean of criterion points (+1 favorable, 0 neutral, -1 unfavorable) over the
# criteria that could be evaluated. favorable needs score >= STANCE_BAND, at least one core
# criterion favorable and none unfavorable; unfavorable is symmetric; otherwise neutral.
STANCE_BAND = 0.25

# --- ARGO (value) v1 -----------------------------------------------------------------------
ARGO_VERSION = "1.0.0"
ARGO_PE_FAVORABLE_MAX = 15.0      # P/E <= 15: low price relative to earnings (heuristic)
ARGO_PE_UNFAVORABLE_MIN = 25.0    # P/E >= 25: expensive relative to earnings
ARGO_MARGIN_FAVORABLE_MIN = 0.15  # profit margin >= 15%: earnings quality
ARGO_MARGIN_UNFAVORABLE_MAX = 0.05  # profit margin < 5% (negative included)
ARGO_WEIGHTS = {"pe_valuation": 0.5, "margin_quality": 0.3, "value_trap": 0.2}

# --- NOVA (growth) v1 ----------------------------------------------------------------------
NOVA_VERSION = "1.0.0"
NOVA_REVENUE_FAVORABLE_MIN = 0.15
NOVA_REVENUE_UNFAVORABLE_MAX = 0.05     # < 5% (negative included)
NOVA_EARNINGS_FAVORABLE_MIN = 0.15
NOVA_EARNINGS_UNFAVORABLE_MAX = 0.0     # < 0: earnings shrinking
NOVA_MARGIN_FAVORABLE_MIN = 0.15
NOVA_MARGIN_UNFAVORABLE_MAX = 0.05
NOVA_WEIGHTS = {"revenue_growth": 0.4, "earnings_growth": 0.3, "margin_sustainability": 0.3}

# --- VECTOR (momentum) v1 ------------------------------------------------------------------
VECTOR_VERSION = "1.0.0"
VECTOR_RETURN_LONG_THRESHOLD = 0.10     # |return_60d| >= 10%
VECTOR_RETURN_SHORT_THRESHOLD = 0.03    # |return_20d| >= 3%
VECTOR_VOLUME_CONFIRMATION_MIN = 1.2    # 20d avg volume >= 1.2 x 60d avg volume
VECTOR_RISK_VOLATILITY_20D = 0.40       # recent annualized volatility flagged as a risk
VECTOR_WEIGHTS = {"return_60d": 0.35, "trend_alignment": 0.25, "return_20d": 0.25, "volume_confirmation": 0.15}

# --- AEGIS (capital preservation) v1 -------------------------------------------------------
AEGIS_VERSION = "1.0.0"
AEGIS_VOLATILITY_FAVORABLE_MAX = 0.25
AEGIS_VOLATILITY_UNFAVORABLE_MIN = 0.45
AEGIS_MAX_DRAWDOWN_FAVORABLE_MAX = 0.15
AEGIS_MAX_DRAWDOWN_UNFAVORABLE_MIN = 0.30
AEGIS_CURRENT_DRAWDOWN_FAVORABLE_MAX = 0.05
AEGIS_CURRENT_DRAWDOWN_UNFAVORABLE_MIN = 0.20
AEGIS_MARGIN_FAVORABLE_MIN = 0.15
AEGIS_MARGIN_UNFAVORABLE_MAX = 0.05
AEGIS_RISING_VOLATILITY_RATIO = 1.5      # risk flag: volatility_20d / volatility_annualized >= 1.5
AEGIS_WEIGHTS = {"volatility": 0.35, "max_drawdown": 0.35, "current_drawdown": 0.15, "margin_cushion": 0.15}


def validate_config() -> None:
    """Import-time sanity checks: weights positive and summing to 1, ordered thresholds."""
    for name, weights in {"ARGO": ARGO_WEIGHTS, "NOVA": NOVA_WEIGHTS, "VECTOR": VECTOR_WEIGHTS,
                          "AEGIS": AEGIS_WEIGHTS}.items():
        if any(w <= 0 for w in weights.values()) or abs(sum(weights.values()) - 1.0) > 1e-9:
            raise ValueError(f"{name} weights must be positive and sum to 1")
    ordered = [
        (ARGO_PE_FAVORABLE_MAX, ARGO_PE_UNFAVORABLE_MIN),
        (ARGO_MARGIN_UNFAVORABLE_MAX, ARGO_MARGIN_FAVORABLE_MIN),
        (NOVA_REVENUE_UNFAVORABLE_MAX, NOVA_REVENUE_FAVORABLE_MIN),
        (NOVA_EARNINGS_UNFAVORABLE_MAX, NOVA_EARNINGS_FAVORABLE_MIN),
        (AEGIS_VOLATILITY_FAVORABLE_MAX, AEGIS_VOLATILITY_UNFAVORABLE_MIN),
        (AEGIS_MAX_DRAWDOWN_FAVORABLE_MAX, AEGIS_MAX_DRAWDOWN_UNFAVORABLE_MIN),
        (AEGIS_CURRENT_DRAWDOWN_FAVORABLE_MAX, AEGIS_CURRENT_DRAWDOWN_UNFAVORABLE_MIN),
    ]
    if any(low >= high for low, high in ordered):
        raise ValueError("threshold pairs must be strictly ordered")
    if not 0 < STANCE_BAND < 1:
        raise ValueError("STANCE_BAND must be in (0, 1)")


validate_config()
