"""Deterministic pre-trade checks, run when preparing AND again when confirming.

Inputs are broker snapshots (account, clock, asset). Capacity (buying power,
shares) lives in reservations.py.
Missing data needed for a decision is treated as failure, never as "safe".
Passing these checks does not reserve funds or guarantee acceptance: Alpaca
remains the final authority. ATLAS's synthetic prices are never used here.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

from app.paper.config import PaperSettings
from app.paper.models import Check, ErrorCode, PaperError, Side


def dec(value: Any) -> Decimal | None:
    """Parse a broker decimal string. None for missing; never a float, never NaN/inf."""
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _fail(checks: list[Check], name: str, detail: str, code: ErrorCode, message: str) -> None:
    checks.append(Check(name=name, passed=False, detail=detail))
    raise PaperError(code, message)


def run_checks(settings: PaperSettings, side: Side, symbol: str, notional: Decimal | None,
               qty: Decimal | None, account: dict, clock: dict, asset: dict | None) -> list[Check]:
    """Static checks: account, session, asset, fractional rules and the per-order limit."""
    checks: list[Check] = []

    # Account
    if account.get("status") != "ACTIVE" or account.get("trading_blocked") is not False \
            or account.get("account_blocked") is not False:
        _fail(checks, "account_tradable", "account is not active or is blocked",
              ErrorCode.ACCOUNT_NOT_TRADABLE, "The paper account cannot trade right now.")
    checks.append(Check(name="account_tradable", passed=True, detail="paper account active, not blocked"))

    # Market session (initial scope: regular session only)
    if clock.get("is_open") is not True:
        _fail(checks, "market_open", "market is closed", ErrorCode.MARKET_CLOSED,
              "The market is closed. Paper orders are only prepared during the regular session.")
    checks.append(Check(name="market_open", passed=True, detail="regular session open"))

    # Asset
    if asset is None or asset.get("class") != "us_equity" or asset.get("status") != "active" \
            or asset.get("tradable") is not True:
        _fail(checks, "asset_tradable", f"{symbol} is unknown, inactive or not tradable",
              ErrorCode.ASSET_NOT_SUPPORTED, f"{symbol} is not a tradable US equity on Alpaca.")
    checks.append(Check(name="asset_tradable", passed=True, detail=f"{symbol} is an active US equity"))

    fractional_needed = side is Side.BUY or (qty is not None and qty != qty.to_integral_value())
    if fractional_needed:
        if asset.get("fractionable") is not True:
            reason = "notional orders" if side is Side.BUY else "fractional quantities"
            _fail(checks, "fractionable", f"{symbol} does not support {reason}",
                  ErrorCode.FRACTIONAL_NOT_SUPPORTED,
                  f"{symbol} does not support {reason}. No other order type is substituted.")
        checks.append(Check(name="fractionable", passed=True, detail=f"{symbol} is fractionable"))

    if side is Side.BUY:
        if notional > settings.max_order_notional:
            _fail(checks, "order_limit", f"{notional} exceeds {settings.max_order_notional}",
                  ErrorCode.ORDER_LIMIT_EXCEEDED,
                  f"The amount exceeds the configured limit of {settings.max_order_notional} USD.")
        checks.append(Check(name="order_limit", passed=True,
                            detail=f"{notional} <= {settings.max_order_notional} USD"))
    # Buying power and position capacity are decided in reservations.py, together
    # with local reservations (and re-checked inside the claim transaction).

    return checks
