"""Four explicit, deterministic strategies over the shared AgentSnapshot.

Each criterion maps published metric values to favorable (+1), neutral (0) or unfavorable (-1),
or reports that it could not be evaluated (missing input, ratio not interpretable). A missing
metric is never favorable and never 0. No LLM is involved; nothing here places or proposes orders.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.agents import config as C

Values = dict[str, float | None]
POINTS = {"favorable": 1, "neutral": 0, "unfavorable": -1}


@dataclass(frozen=True)
class Assessment:
    direction: str | None   # favorable | neutral | unfavorable | None (not evaluated)
    reason: str | None      # when not evaluated: "missing" | "not_interpretable"
    statement: str


@dataclass(frozen=True)
class Criterion:
    id: str
    label: str
    weight: float
    core: bool
    metrics: tuple[str, ...]
    rule: str
    assess: Callable[[Values], Assessment]


@dataclass(frozen=True)
class RiskRule:
    id: str
    metrics: tuple[str, ...]
    check: Callable[[Values], str | None]   # statement when the risk applies


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    style: str
    version: str
    lens: str
    stance_meaning: str
    criteria: tuple[Criterion, ...]
    risks: tuple[RiskRule, ...]
    limitations: tuple[str, ...]


# --- formatting (values in JSON stay decimals; text shows percent with 2 decimals) ----------
def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def mult(x: float) -> str:
    return f"{x:.2f}x"


def higher_better(value: float, fav_min: float, unfav_below: float) -> str:
    if value >= fav_min:
        return "favorable"
    if value < unfav_below:
        return "unfavorable"
    return "neutral"


def lower_better(value: float, fav_max: float, unfav_min: float) -> str:
    if value <= fav_max:
        return "favorable"
    if value >= unfav_min:
        return "unfavorable"
    return "neutral"


def _a(direction: str, statement: str) -> Assessment:
    return Assessment(direction, None, statement)


# --- ARGO: value ---------------------------------------------------------------------------
def _argo_pe(v: Values) -> Assessment:
    pe = v["pe_ratio"]
    if pe <= 0:
        return Assessment(None, "not_interpretable",
                          f"P/E {mult(pe)} implies zero or negative earnings; it is not read as cheap.")
    d = lower_better(pe, C.ARGO_PE_FAVORABLE_MAX, C.ARGO_PE_UNFAVORABLE_MIN)
    text = {"favorable": "low price relative to earnings", "neutral": "moderate price relative to earnings",
            "unfavorable": "expensive relative to earnings"}[d]
    return _a(d, f"P/E {mult(pe)}: {text}.")


def _argo_margin(v: Values) -> Assessment:
    m = v["profit_margin"]
    d = higher_better(m, C.ARGO_MARGIN_FAVORABLE_MIN, C.ARGO_MARGIN_UNFAVORABLE_MAX)
    return _a(d, f"Profit margin {pct(m)} as an earnings-quality signal.")


def _argo_trap(v: Values) -> Assessment:
    g = v["earnings_growth"]
    if g < 0:
        return _a("unfavorable", f"Earnings growth {pct(g)}: shrinking earnings can make a low multiple a value trap.")
    return _a("neutral", f"Earnings growth {pct(g)}: earnings are not shrinking (no value-trap signal).")


ARGO = Strategy(
    id="argo", name="ARGO", style="value", version=C.ARGO_VERSION,
    lens="Price relative to earnings, earnings quality and value-trap check (limited P/E lens).",
    stance_meaning="favorable = available valuation evidence is attractive for a value lens; "
                   "not an estimate of intrinsic value and not an order.",
    criteria=(
        Criterion("pe_valuation", "P/E valuation", C.ARGO_WEIGHTS["pe_valuation"], True, ("pe_ratio",),
                  f"P/E <= {C.ARGO_PE_FAVORABLE_MAX:g} favorable; >= {C.ARGO_PE_UNFAVORABLE_MIN:g} unfavorable; "
                  "P/E <= 0 not interpretable", _argo_pe),
        Criterion("margin_quality", "Earnings quality (margin)", C.ARGO_WEIGHTS["margin_quality"], False,
                  ("profit_margin",), f"margin >= {C.ARGO_MARGIN_FAVORABLE_MIN} favorable; "
                  f"< {C.ARGO_MARGIN_UNFAVORABLE_MAX} unfavorable (decimal)", _argo_margin),
        Criterion("value_trap", "Value-trap check", C.ARGO_WEIGHTS["value_trap"], False, ("earnings_growth",),
                  "earnings growth < 0 unfavorable; otherwise neutral (decimal)", _argo_trap),
    ),
    risks=(
        RiskRule("argo.negative_earnings", ("pe_ratio",),
                 lambda v: "P/E is zero or negative: earnings do not support a valuation multiple."
                 if v["pe_ratio"] is not None and v["pe_ratio"] <= 0 else None),
    ),
    limitations=(
        "No book value, cash flow or debt in the dataset: no P/B, FCF yield or balance-sheet strength.",
        "No intrinsic value or margin of safety is calculated (no DCF, no hidden assumptions).",
        "P/E is a single undated figure from the dataset; thresholds are heuristics, not calibrated.",
    ),
)


# --- NOVA: growth --------------------------------------------------------------------------
def _nova_revenue(v: Values) -> Assessment:
    g = v["revenue_growth"]
    d = higher_better(g, C.NOVA_REVENUE_FAVORABLE_MIN, C.NOVA_REVENUE_UNFAVORABLE_MAX)
    return _a(d, f"Revenue growth {pct(g)}.")


def _nova_earnings(v: Values) -> Assessment:
    g = v["earnings_growth"]
    d = higher_better(g, C.NOVA_EARNINGS_FAVORABLE_MIN, C.NOVA_EARNINGS_UNFAVORABLE_MAX)
    return _a(d, f"Earnings growth {pct(g)}.")


def _nova_margin(v: Values) -> Assessment:
    m = v["profit_margin"]
    d = higher_better(m, C.NOVA_MARGIN_FAVORABLE_MIN, C.NOVA_MARGIN_UNFAVORABLE_MAX)
    return _a(d, f"Profit margin {pct(m)} as a sustainability signal for growth.")


NOVA = Strategy(
    id="nova", name="NOVA", style="growth", version=C.NOVA_VERSION,
    lens="Revenue and earnings growth and whether margins can sustain it. Does not use P/E or price momentum.",
    stance_meaning="favorable = reported growth looks strong and supported by margins; not a forecast and not an order.",
    criteria=(
        Criterion("revenue_growth", "Revenue growth", C.NOVA_WEIGHTS["revenue_growth"], True, ("revenue_growth",),
                  f">= {C.NOVA_REVENUE_FAVORABLE_MIN} favorable; < {C.NOVA_REVENUE_UNFAVORABLE_MAX} unfavorable "
                  "(decimal)", _nova_revenue),
        Criterion("earnings_growth", "Earnings growth", C.NOVA_WEIGHTS["earnings_growth"], False, ("earnings_growth",),
                  f">= {C.NOVA_EARNINGS_FAVORABLE_MIN} favorable; < {C.NOVA_EARNINGS_UNFAVORABLE_MAX:g} unfavorable "
                  "(decimal)", _nova_earnings),
        Criterion("margin_sustainability", "Margin sustainability", C.NOVA_WEIGHTS["margin_sustainability"], False,
                  ("profit_margin",), f">= {C.NOVA_MARGIN_FAVORABLE_MIN} favorable; < {C.NOVA_MARGIN_UNFAVORABLE_MAX} "
                  "unfavorable (decimal)", _nova_margin),
    ),
    risks=(
        RiskRule("nova.growth_not_reaching_earnings", ("revenue_growth", "earnings_growth"),
                 lambda v: "Revenue grows while earnings shrink: growth is not reaching earnings."
                 if None not in (v["revenue_growth"], v["earnings_growth"]) and v["revenue_growth"] > 0
                 and v["earnings_growth"] < 0 else None),
        RiskRule("nova.unprofitable", ("profit_margin",),
                 lambda v: "Negative profit margin: growth is not yet profitable."
                 if v["profit_margin"] is not None and v["profit_margin"] < 0 else None),
    ),
    limitations=(
        "Growth figures are single-period, undated dataset values: no multi-year history to judge persistence.",
        "No debt or cash-flow data: financing constraints on growth cannot be assessed.",
        "A high P/E is not treated as evidence of growth; price momentum is not used as a substitute.",
    ),
)


# --- VECTOR: momentum ----------------------------------------------------------------------
def _vector_r60(v: Values) -> Assessment:
    r = v["return_60d"]
    t = C.VECTOR_RETURN_LONG_THRESHOLD
    d = "favorable" if r >= t else "unfavorable" if r <= -t else "neutral"
    return _a(d, f"60-bar return {pct(r)}.")


def _vector_r20(v: Values) -> Assessment:
    r = v["return_20d"]
    t = C.VECTOR_RETURN_SHORT_THRESHOLD
    d = "favorable" if r >= t else "unfavorable" if r <= -t else "neutral"
    return _a(d, f"20-bar return {pct(r)}.")


def _vector_trend(v: Values) -> Assessment:
    p, s = v["price_vs_sma20"], v["sma20_vs_sma50"]
    if p > 0 and s > 0:
        return _a("favorable", f"Price {pct(p)} above SMA20 and SMA20 {pct(s)} above SMA50: aligned uptrend.")
    if p < 0 and s < 0:
        return _a("unfavorable", f"Price {pct(p)} vs SMA20 and SMA20 {pct(s)} vs SMA50: aligned downtrend.")
    return _a("neutral", f"Price vs SMA20 {pct(p)} and SMA20 vs SMA50 {pct(s)}: averages not aligned.")


def _vector_volume(v: Values) -> Assessment:
    ratio, r20 = v["volume_ratio_20_60"], v["return_20d"]
    if ratio >= C.VECTOR_VOLUME_CONFIRMATION_MIN and r20 > 0:
        return _a("favorable", f"Volume ratio {ratio:.2f} with a rising 20-bar return: volume confirms the move.")
    if ratio >= C.VECTOR_VOLUME_CONFIRMATION_MIN and r20 < 0:
        return _a("unfavorable", f"Volume ratio {ratio:.2f} with a falling 20-bar return: selling pressure.")
    return _a("neutral", f"Volume ratio {ratio:.2f}: no volume confirmation.")


def _vector_divergence(v: Values) -> str | None:
    r20, r60 = v["return_20d"], v["return_60d"]
    if r20 is None or r60 is None:
        return None
    if (r60 >= C.VECTOR_RETURN_LONG_THRESHOLD and r20 <= -C.VECTOR_RETURN_SHORT_THRESHOLD) or \
       (r60 <= -C.VECTOR_RETURN_LONG_THRESHOLD and r20 >= C.VECTOR_RETURN_SHORT_THRESHOLD):
        return f"20-bar return {pct(r20)} runs against the 60-bar return {pct(r60)}: the move may be reversing."
    return None


VECTOR = Strategy(
    id="vector", name="VECTOR", style="momentum", version=C.VECTOR_VERSION,
    lens="Strength and direction of past price movement: 60/20-bar returns, moving-average alignment, volume.",
    stance_meaning="favorable = past price movement is strong and aligned; it does not predict future returns "
                   "and is not an order.",
    criteria=(
        Criterion("return_60d", "60-bar momentum", C.VECTOR_WEIGHTS["return_60d"], True, ("return_60d",),
                  f">= +{C.VECTOR_RETURN_LONG_THRESHOLD} favorable; <= -{C.VECTOR_RETURN_LONG_THRESHOLD} "
                  "unfavorable (decimal; needs 61 bars)", _vector_r60),
        Criterion("trend_alignment", "Moving-average alignment", C.VECTOR_WEIGHTS["trend_alignment"], True,
                  ("price_vs_sma20", "sma20_vs_sma50"),
                  "price > SMA20 > SMA50 favorable; price < SMA20 < SMA50 unfavorable (needs 50 bars)", _vector_trend),
        Criterion("return_20d", "20-bar momentum", C.VECTOR_WEIGHTS["return_20d"], False, ("return_20d",),
                  f">= +{C.VECTOR_RETURN_SHORT_THRESHOLD} favorable; <= -{C.VECTOR_RETURN_SHORT_THRESHOLD} "
                  "unfavorable (decimal; needs 21 bars)", _vector_r20),
        Criterion("volume_confirmation", "Volume confirmation", C.VECTOR_WEIGHTS["volume_confirmation"], False,
                  ("volume_ratio_20_60", "return_20d"),
                  f"ratio >= {C.VECTOR_VOLUME_CONFIRMATION_MIN} confirms the 20-bar direction; otherwise neutral "
                  "(needs 60 bars)", _vector_volume),
    ),
    risks=(
        RiskRule("vector.high_recent_volatility", ("volatility_20d",),
                 lambda v: f"Recent annualized volatility {pct(v['volatility_20d'])}: momentum can reverse sharply."
                 if v["volatility_20d"] is not None and v["volatility_20d"] >= C.VECTOR_RISK_VOLATILITY_20D else None),
        RiskRule("vector.divergence", ("return_20d", "return_60d"), _vector_divergence),
    ),
    limitations=(
        "Momentum describes past movement only; it is not a prediction of returns.",
        "Prices and volumes are a synthetic random walk; no transaction costs or liquidity are modeled.",
    ),
)


# --- AEGIS: capital preservation -----------------------------------------------------------
def _aegis_vol(v: Values) -> Assessment:
    x = v["volatility_annualized"]
    d = lower_better(x, C.AEGIS_VOLATILITY_FAVORABLE_MAX, C.AEGIS_VOLATILITY_UNFAVORABLE_MIN)
    return _a(d, f"Observed annualized volatility {pct(x)}.")


def _aegis_mdd(v: Values) -> Assessment:
    x = v["max_drawdown"]
    d = lower_better(x, C.AEGIS_MAX_DRAWDOWN_FAVORABLE_MAX, C.AEGIS_MAX_DRAWDOWN_UNFAVORABLE_MIN)
    return _a(d, f"Observed maximum drawdown {pct(x)}.")


def _aegis_cdd(v: Values) -> Assessment:
    x = v["current_drawdown"]
    d = lower_better(x, C.AEGIS_CURRENT_DRAWDOWN_FAVORABLE_MAX, C.AEGIS_CURRENT_DRAWDOWN_UNFAVORABLE_MIN)
    return _a(d, f"Current distance below the window high {pct(x)}.")


def _aegis_margin(v: Values) -> Assessment:
    m = v["profit_margin"]
    d = higher_better(m, C.AEGIS_MARGIN_FAVORABLE_MIN, C.AEGIS_MARGIN_UNFAVORABLE_MAX)
    return _a(d, f"Profit margin {pct(m)} as an operating cushion (only financial-strength input available).")


AEGIS = Strategy(
    id="aegis", name="AEGIS", style="defensive", version=C.AEGIS_VERSION,
    lens="Observed risk exposure: volatility, drawdowns and the operating cushion available in the data.",
    stance_meaning="favorable = lower observed historical risk exposure; it is NOT a statement that the stock is "
                   "safe, does not guarantee capital preservation and is not an order.",
    criteria=(
        Criterion("volatility", "Observed volatility", C.AEGIS_WEIGHTS["volatility"], True, ("volatility_annualized",),
                  f"<= {C.AEGIS_VOLATILITY_FAVORABLE_MAX} favorable; >= {C.AEGIS_VOLATILITY_UNFAVORABLE_MIN} "
                  "unfavorable (decimal, annualized)", _aegis_vol),
        Criterion("max_drawdown", "Maximum drawdown", C.AEGIS_WEIGHTS["max_drawdown"], True, ("max_drawdown",),
                  f"<= {C.AEGIS_MAX_DRAWDOWN_FAVORABLE_MAX} favorable; >= {C.AEGIS_MAX_DRAWDOWN_UNFAVORABLE_MIN} "
                  "unfavorable (decimal)", _aegis_mdd),
        Criterion("current_drawdown", "Current drawdown", C.AEGIS_WEIGHTS["current_drawdown"], False,
                  ("current_drawdown",), f"<= {C.AEGIS_CURRENT_DRAWDOWN_FAVORABLE_MAX} favorable; >= "
                  f"{C.AEGIS_CURRENT_DRAWDOWN_UNFAVORABLE_MIN} unfavorable (decimal)", _aegis_cdd),
        Criterion("margin_cushion", "Operating cushion (margin)", C.AEGIS_WEIGHTS["margin_cushion"], False,
                  ("profit_margin",), f">= {C.AEGIS_MARGIN_FAVORABLE_MIN} favorable; < {C.AEGIS_MARGIN_UNFAVORABLE_MAX} "
                  "unfavorable (decimal)", _aegis_margin),
    ),
    risks=(
        RiskRule("aegis.rising_volatility", ("volatility_20d", "volatility_annualized"),
                 lambda v: f"Recent volatility {pct(v['volatility_20d'])} is at least {C.AEGIS_RISING_VOLATILITY_RATIO}x the full-window "
                           f"{pct(v['volatility_annualized'])}."
                 if None not in (v["volatility_20d"], v["volatility_annualized"]) and v["volatility_annualized"] > 0
                 and round(v["volatility_20d"] / v["volatility_annualized"], C.METRIC_DECIMALS)
                 >= C.AEGIS_RISING_VOLATILITY_RATIO else None),
    ),
    limitations=(
        "Observed past risk is not future protection; no position is ever safe or guaranteed.",
        "No portfolio, diversification, liquidity or debt data: exposure is judged for one symbol only.",
        "No hedging, derivatives or short selling is recommended.",
    ),
)

# Fixed registry: order is stable and ids are those of the published frontend profiles.
REGISTRY: tuple[Strategy, ...] = (ARGO, NOVA, VECTOR, AEGIS)
