"""Analysis service.

PHASE 1 (SIMULATED): returns a fixed, realistic-looking response for any
known demo symbol. The values are placeholders, flagged with
isSimulated=True. Phase 2+ replaces this with the technical, risk and
fundamental analyzers and the supervisor. No value here reflects the market.
"""

from app.catalog import lookup_company_name
from app.schemas import AnalyzeResponse, Signals


def run_simulated_analysis(symbol: str) -> AnalyzeResponse | None:
    """Return a simulated analysis for a known symbol, or None if unknown."""
    company_name = lookup_company_name(symbol)
    if company_name is None:
        return None

    return AnalyzeResponse(
        symbol=symbol,
        companyName=company_name,
        recommendation="HOLD",
        confidence=0.72,
        summary="Simulated analysis for Phase 1",
        signals=Signals(momentum="neutral", risk="moderate", trend="positive"),
        isSimulated=True,
    )
