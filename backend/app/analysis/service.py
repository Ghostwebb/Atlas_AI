"""Analysis service: orchestrates provider -> analyzers -> aggregator -> response.

No HTTP concerns live here. The API layer only validates input and maps results
to status codes.
"""

import pandas as pd

from app.analysis.aggregate import aggregate
from app.analysis.fundamental import FundamentalResult, analyze_fundamentals
from app.analysis.narrative import build_explanation, build_summary
from app.analysis.risk import RiskResult, analyze_risk
from app.analysis.technical import MomentumResult, TrendResult, analyze_momentum, analyze_trend
from app.data.provider import MarketDataProvider
from app.schemas import (
    AnalysisDetails,
    AnalyzeResponse,
    FundamentalAnalysis,
    MomentumAnalysis,
    RiskAnalysis,
    Signals,
    TrendAnalysis,
)


def analyze_symbol(symbol: str, provider: MarketDataProvider) -> AnalyzeResponse | None:
    """Run the full analysis for `symbol`. Returns None if the provider does not know it."""
    snapshot = provider.get_snapshot(symbol)
    if snapshot is None:
        return None

    closes = pd.Series([bar.close for bar in snapshot.bars], dtype=float)

    momentum = analyze_momentum(closes)
    trend = analyze_trend(closes)
    risk = analyze_risk(closes)
    fundamental = analyze_fundamentals(snapshot.fundamentals)

    result = aggregate(
        {
            "momentum": momentum.score if momentum else None,
            "trend": trend.score if trend else None,
            "risk": risk.signal_score if risk else None,
            "fundamental": fundamental.score if fundamental else None,
        }
    )

    return AnalyzeResponse(
        symbol=snapshot.symbol,
        companyName=snapshot.company_name,
        recommendation=result.recommendation,
        confidence=result.confidence,
        summary=build_summary(
            snapshot.company_name, momentum, trend, risk, result.recommendation
        ),
        explanation=build_explanation(
            momentum, trend, risk, fundamental, result, snapshot.data_issues
        ),
        signals=_signals(momentum, trend, risk, fundamental),
        analysis=_details(momentum, trend, risk, fundamental),
        isSimulated=True,
        dataSource=snapshot.data_source,
        dataAsOf=snapshot.as_of.isoformat() if snapshot.as_of else None,
        dataIssues=snapshot.data_issues,
    )


def _signals(
    momentum: MomentumResult | None,
    trend: TrendResult | None,
    risk: RiskResult | None,
    fundamental: FundamentalResult | None,
) -> Signals:
    return Signals(
        momentum=momentum.label if momentum else "unavailable",
        trend=trend.label if trend else "unavailable",
        risk=risk.label if risk else "unavailable",
        fundamental=fundamental.label if fundamental else "unavailable",
    )


def _details(
    momentum: MomentumResult | None,
    trend: TrendResult | None,
    risk: RiskResult | None,
    fundamental: FundamentalResult | None,
) -> AnalysisDetails:
    return AnalysisDetails(
        momentum=MomentumAnalysis(
            label=momentum.label if momentum else "unavailable",
            score=momentum.score if momentum else None,
            changePercent=momentum.change_percent if momentum else None,
        ),
        trend=TrendAnalysis(
            label=trend.label if trend else "unavailable",
            score=trend.score if trend else None,
            shortMovingAverage=trend.short_moving_average if trend else None,
            longMovingAverage=trend.long_moving_average if trend else None,
            priceVsShortMovingAverage=trend.price_vs_short_ma if trend else None,
            priceVsLongMovingAverage=trend.price_vs_long_ma if trend else None,
        ),
        risk=RiskAnalysis(
            label=risk.label if risk else "unavailable",
            score=risk.risk_score if risk else None,
            volatility=risk.volatility if risk else None,
            maxDrawdown=risk.max_drawdown if risk else None,
        ),
        fundamental=FundamentalAnalysis(
            label=fundamental.label if fundamental else "unavailable",
            score=fundamental.score if fundamental else None,
            metricsUsed=fundamental.metrics_used if fundamental else 0,
            revenueGrowth=fundamental.revenue_growth if fundamental else None,
            profitMargin=fundamental.profit_margin if fundamental else None,
            peRatio=fundamental.pe_ratio if fundamental else None,
            earningsGrowth=fundamental.earnings_growth if fundamental else None,
        ),
    )
