"""Capacity policy: how much cash or how many shares a new ATLAS order may commit.

Inputs (all read fresh from Alpaca before each prepare/confirm, outside any DB transaction):
  A  account snapshot (cash, non_marginable_buying_power)
  P  position snapshot for the symbol (qty, qty_available)
  L  list of OPEN orders (status=open, up to 500; a full page => cannot prove completeness)

Alpaca documents that open buy orders reduce buying power, that sell orders do not
replenish it until executed, and that qty_available = qty minus open orders. It
does not document that A/P and L are mutually consistent or how fresh A/P are.
So ATLAS never trusts a single number:

  broker cash available   = min(non_marginable_buying_power,
                                cash - sum(open buy notional holds in L))
  broker shares available = min(qty_available,
                                qty - sum(open sell remaining qty in L for the symbol))

Each min() term covers the other one being stale: an order that L shows open is
subtracted by the second term even if the snapshot predates it, and an order the
snapshot already reflects is not subtracted twice by the first term. Open orders
whose hold cannot be computed (qty-based buys, notional sells, placed outside
ATLAS) are left to the first term.

Local commitments: every ACTIVE reservation (held or acknowledged) whose
client_order_id is NOT in L is subtracted again locally, because nothing proves
the broker snapshot includes it:
  held          full amount (uncertain or in-flight submissions included)
  acknowledged  amount - consumed (consumed = shares filled / filled cost observed)
Reservations whose order IS in L are covered by the min() above and are not
subtracted twice.

Decision:
  requested > broker available                    -> INSUFFICIENT_* (definitive)
  requested > broker available - local commitments
      and a blocking reservation is uncertain     -> RECONCILIATION_REQUIRED
      otherwise                                   -> RESOURCE_RESERVED (temporary)
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.paper.models import Check, ErrorCode, PaperError, Side
from app.paper.validation import dec

OPEN_ORDERS_PAGE = 500  # Alpaca's maximum page size for GET /v2/orders


@dataclass(frozen=True)
class Capacity:
    resource_type: str        # cash | shares
    symbol: str | None
    broker_available: Decimal
    detail: str


def require_complete(open_orders: list[dict[str, Any]]) -> None:
    if len(open_orders) >= OPEN_ORDERS_PAGE:
        raise PaperError(ErrorCode.RECONCILIATION_REQUIRED,
                         "Too many open orders to verify availability. Check your orders first.")


def _filled_cost(order: dict[str, Any]) -> Decimal:
    qty, price = dec(order.get("filled_qty")), dec(order.get("filled_avg_price"))
    return qty * price if qty is not None and price is not None else Decimal(0)


def broker_cash(account: dict[str, Any], open_orders: list[dict[str, Any]]) -> Capacity:
    nmbp, cash = dec(account.get("non_marginable_buying_power")), dec(account.get("cash"))
    if nmbp is None or cash is None:
        raise PaperError(ErrorCode.BROKER_UNAVAILABLE,
                         "The broker did not report buying power; the order cannot be validated.")
    holds = Decimal(0)
    for order in open_orders:
        notional = dec(order.get("notional"))
        if order.get("side") == "buy" and notional is not None:
            holds += max(notional - _filled_cost(order), Decimal(0))
    available = min(nmbp, cash - holds)
    return Capacity("cash", None, available,
                    f"min(non-marginable buying power {nmbp}, cash {cash} - open buy holds {holds}) = {available}")


def broker_shares(position: dict[str, Any] | None, open_orders: list[dict[str, Any]], symbol: str) -> Capacity:
    if position is None or position.get("side") != "long":
        raise PaperError(ErrorCode.INSUFFICIENT_POSITION,
                         f"There is no long {symbol} position to reduce. Short sales are not allowed.")
    qty, qty_available = dec(position.get("qty")), dec(position.get("qty_available"))
    if qty is None or qty_available is None:
        raise PaperError(ErrorCode.BROKER_UNAVAILABLE,
                         "The broker did not report the available quantity; the order cannot be validated.")
    held = Decimal(0)
    for order in open_orders:
        order_qty = dec(order.get("qty"))
        if order.get("symbol") == symbol and order.get("side") == "sell" and order_qty is not None:
            held += max(order_qty - (dec(order.get("filled_qty")) or Decimal(0)), Decimal(0))
    available = min(qty_available, qty - held)
    return Capacity("shares", symbol, available,
                    f"min(qty_available {qty_available}, qty {qty} - open sell remaining {held}) = {available}")


def remaining(row: dict[str, Any]) -> Decimal:
    amount = Decimal(row["amount"])
    if row["state"] == "held":
        return amount
    return max(amount - Decimal(row["consumed"]), Decimal(0))


def local_commitments(rows: list[dict[str, Any]], open_client_ids: set[str],
                      uncertain: set[str]) -> tuple[Decimal, bool]:
    """Sum of local commitments not visible in L, and whether any of them is uncertain."""
    total, has_uncertain = Decimal(0), False
    for row in rows:
        if row["client_order_id"] in open_client_ids:
            continue
        total += remaining(row)
        has_uncertain |= row["proposal_id"] in uncertain
    return total, has_uncertain


def decide(side: Side, requested: Decimal, capacity: Capacity, rows: list[dict[str, Any]],
           open_client_ids: set[str], uncertain: set[str]) -> Check:
    name = "buying_power" if side is Side.BUY else "position"
    if requested > capacity.broker_available:
        if side is Side.BUY:
            raise PaperError(ErrorCode.INSUFFICIENT_BUYING_POWER,
                             "Not enough non-marginable buying power in the paper account.")
        raise PaperError(ErrorCode.INSUFFICIENT_POSITION,
                         "The quantity exceeds the shares available after open orders.")
    local, has_uncertain = local_commitments(rows, open_client_ids, uncertain)
    free = capacity.broker_available - local
    if requested > free:
        if has_uncertain:
            raise PaperError(ErrorCode.RECONCILIATION_REQUIRED,
                             "An earlier order has an uncertain result. Check its status before another operation.")
        if side is Side.BUY:
            raise PaperError(ErrorCode.RESOURCE_RESERVED,
                             "Budget is reserved by a pending operation. Wait for it to finish or cancel it.")
        raise PaperError(ErrorCode.RESOURCE_RESERVED,
                         "Shares are committed by another order. Wait for it to finish or cancel it.")
    return Check(name=name, passed=True,
                 detail=f"{requested} <= {free} ({capacity.detail}; local commitments {local})")
