"""Deterministic pre-trade checks, run when preparing AND again when confirming.

Inputs are broker snapshots (account, clock, asset, position) plus local state.
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
               qty: Decimal | None, account: dict, clock: dict, asset: dict | None,
               position: dict | None, committed_sell_qty: list[str]) -> list[Check]:
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
        # No leverage requested by the app: the order must fit non-marginable buying power.
        available = dec(account.get("non_marginable_buying_power"))
        if available is None:
            _fail(checks, "buying_power", "buying power not reported", ErrorCode.BROKER_UNAVAILABLE,
                  "The broker did not report buying power; the order cannot be validated.")
        if notional > available:
            _fail(checks, "buying_power", f"{notional} > {available}", ErrorCode.INSUFFICIENT_BUYING_POWER,
                  "Not enough non-marginable buying power in the paper account.")
        checks.append(Check(name="buying_power", passed=True,
                            detail=f"{notional} <= {available} non-marginable buying power"))
    else:
        if position is None or position.get("side") != "long":
            _fail(checks, "position", f"no long position in {symbol}", ErrorCode.INSUFFICIENT_POSITION,
                  f"There is no long {symbol} position to reduce. Short sales are not allowed.")
        available = dec(position.get("qty_available"))
        if available is None:
            _fail(checks, "position", "qty_available not reported", ErrorCode.BROKER_UNAVAILABLE,
                  "The broker did not report the available quantity; the order cannot be validated.")
        committed = sum((dec(q) or Decimal(0) for q in committed_sell_qty), Decimal(0))
        free = available - committed
        if qty > free:
            _fail(checks, "position", f"{qty} > {free} (available {available}, uncertain local sells {committed})",
                  ErrorCode.INSUFFICIENT_POSITION,
                  "The quantity exceeds the shares available after open and pending orders.")
        checks.append(Check(name="position", passed=True,
                            detail=f"{qty} <= {free} (available {available}, uncertain local sells {committed})"))

    return checks
