"""Data quality checks for price bars. Detects errors; never repairs them."""

from app.data.provider import PriceBar


def find_bar_issues(bars: list[PriceBar]) -> list[str]:
    """Return human-readable problems found in a price series (empty if clean)."""
    issues: list[str] = []
    for index, bar in enumerate(bars):
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            issues.append(f"Non-positive price on {bar.date.isoformat()}")
        if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
            issues.append(f"Inconsistent OHLC values on {bar.date.isoformat()}")
        if bar.volume < 0:
            issues.append(f"Negative volume on {bar.date.isoformat()}")
        if index > 0 and bar.date <= bars[index - 1].date:
            issues.append(f"Dates not strictly increasing at {bar.date.isoformat()}")
    return issues
