"""Local demo catalog of supported symbols.

PHASE 1 (SIMULATED): symbol existence is checked against this static list.
It will be replaced in Phase 2 by a real market data provider behind an
abstract provider interface. Nothing here is live market data.
"""

DEMO_CATALOG: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "TSLA": "Tesla, Inc.",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.",
}


def lookup_company_name(symbol: str) -> str | None:
    """Return the company name for a known demo symbol, or None if unknown."""
    return DEMO_CATALOG.get(symbol)
