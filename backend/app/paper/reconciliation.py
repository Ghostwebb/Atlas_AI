"""Mapping Alpaca orders onto local proposals.

An order is only applied to a proposal when client_order_id, symbol and side all
match. The local broker status always mirrors what Alpaca reported; ATLAS never
infers "canceled" or "filled" by itself.
"""

from typing import Any

from app.paper.models import BrokerOrder, BrokerOrderStatus
from app.paper.validation import dec


def order_matches(proposal: dict[str, Any], order: dict[str, Any]) -> bool:
    return (
        order.get("client_order_id") == proposal["client_order_id"]
        and order.get("symbol") == proposal["symbol"]
        and order.get("side") == proposal["side"]
    )


def order_changes(order: dict[str, Any], now: str) -> dict[str, Any]:
    filled_qty = dec(order.get("filled_qty"))
    avg_price = dec(order.get("filled_avg_price"))
    return {
        "submission_status": "submitted",
        "broker_order_id": order["id"],
        "broker_status": BrokerOrderStatus.parse(order.get("status")).value,
        "filled_qty": str(filled_qty) if filled_qty is not None else None,
        "filled_avg_price": str(avg_price) if avg_price is not None else None,
        "updated_at": now,
    }


def to_broker_order(order: dict[str, Any], proposal_id: str | None) -> BrokerOrder:
    return BrokerOrder(
        id=str(order.get("id")),
        clientOrderId=str(order.get("client_order_id") or ""),
        symbol=str(order.get("symbol") or ""),
        side=str(order.get("side") or ""),
        type=str(order.get("type") or order.get("order_type") or ""),
        timeInForce=str(order.get("time_in_force") or ""),
        qty=dec(order.get("qty")),
        notional=dec(order.get("notional")),
        filledQty=dec(order.get("filled_qty")),
        filledAvgPrice=dec(order.get("filled_avg_price")),
        status=BrokerOrderStatus.parse(order.get("status")),
        brokerStatusRaw=str(order.get("status") or ""),
        submittedAt=order.get("submitted_at"),
        filledAt=order.get("filled_at"),
        canceledAt=order.get("canceled_at"),
        proposalId=proposal_id,
    )
