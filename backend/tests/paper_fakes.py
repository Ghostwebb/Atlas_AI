"""In-memory fake of the Alpaca Paper client. No network. Records every call."""

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.paper.client import BrokerConflict, BrokerNotFound, BrokerUnavailable, SubmitOutcome, SubmitResult
from app.paper.config import PaperSettings
from app.paper.repository import Repository
from app.paper.service import PaperTradingService

PAPER_KEY = "PKTESTKEY000000000000"
PAPER_SECRET = "test-secret-value-never-logged"


def settings(**overrides) -> PaperSettings:
    values = dict(enabled=True, api_key=PAPER_KEY, secret_key=PAPER_SECRET,
                  allow_requests_without_origin=False)
    values.update(overrides)
    return PaperSettings(**values)


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class FakeBroker:
    def __init__(self):
        self.calls: list[str] = []
        self.submits: list[dict] = []
        self.account = {"status": "ACTIVE", "currency": "USD", "trading_blocked": False,
                        "account_blocked": False, "cash": "100000", "buying_power": "200000",
                        "non_marginable_buying_power": "100000", "equity": "100000"}
        self.clock = {"is_open": True, "timestamp": "2026-10-05T11:00:00-04:00",
                      "next_open": "2026-10-06T09:30:00-04:00", "next_close": "2026-10-05T16:00:00-04:00"}
        self.assets = {
            "NVDA": {"symbol": "NVDA", "class": "us_equity", "status": "active", "tradable": True, "fractionable": True},
            "BRK.A": {"symbol": "BRK.A", "class": "us_equity", "status": "active", "tradable": True, "fractionable": False},
            "OLD": {"symbol": "OLD", "class": "us_equity", "status": "inactive", "tradable": False, "fractionable": False},
        }
        self.positions: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        # submit behaviour: accept | reject | not_sent | unknown_created | unknown_missing | raise
        self.submit_mode = "accept"
        self.fill_status = "accepted"
        self.fill_qty = "0"
        self.submit_delay = 0.0
        self.cancel_mode = "pending_cancel"  # pending_cancel | filled_race | not_cancelable | not_found
        self.unavailable = False
        self._lock = threading.Lock()

    def _call(self, name: str) -> None:
        with self._lock:
            self.calls.append(name)
        if self.unavailable:
            raise BrokerUnavailable("down")

    def add_position(self, symbol: str, qty: str, qty_available: str | None = None, side: str = "long"):
        self.positions[symbol] = {"symbol": symbol, "side": side, "qty": qty,
                                  "qty_available": qty if qty_available is None else qty_available,
                                  "avg_entry_price": "100", "market_value": "500", "asset_class": "us_equity"}

    # reads
    def get_account(self):
        self._call("get_account")
        return dict(self.account)

    def get_clock(self):
        self._call("get_clock")
        return dict(self.clock)

    def get_asset(self, symbol):
        self._call("get_asset")
        return self.assets.get(symbol)

    def get_position(self, symbol):
        self._call("get_position")
        return self.positions.get(symbol)

    def list_positions(self):
        self._call("list_positions")
        return list(self.positions.values())

    def get_order(self, order_id):
        self._call("get_order")
        order = self.orders.get(order_id)
        return dict(order) if order else None

    def get_order_by_client_id(self, client_order_id):
        self._call("get_order_by_client_id")
        for order in self.orders.values():
            if order["client_order_id"] == client_order_id:
                return dict(order)
        return None

    def list_orders(self, status, limit):
        self._call("list_orders")
        return [dict(o) for o in list(self.orders.values())[:limit]]

    # mutations
    def _store(self, payload: dict) -> dict:
        order = {"id": str(uuid.uuid4()), "client_order_id": payload["client_order_id"],
                 "symbol": payload["symbol"], "side": payload["side"], "type": payload["type"],
                 "time_in_force": payload["time_in_force"], "qty": payload.get("qty"),
                 "notional": payload.get("notional"), "filled_qty": self.fill_qty,
                 "filled_avg_price": "101.25" if self.fill_qty != "0" else None,
                 "status": self.fill_status, "submitted_at": "2026-10-05T15:00:01Z",
                 "filled_at": None, "canceled_at": None}
        self.orders[order["id"]] = order
        return order

    def submit_order(self, payload):
        self._call("submit_order")
        with self._lock:
            self.submits.append(dict(payload))
        if self.submit_delay:
            time.sleep(self.submit_delay)
        mode = self.submit_mode
        if mode == "accept":
            return SubmitResult(SubmitOutcome.ACCEPTED, order=dict(self._store(payload)), http_status=200)
        if mode == "reject":
            return SubmitResult(SubmitOutcome.REJECTED, http_status=403, detail="HTTP 403")
        if mode == "not_sent":
            return SubmitResult(SubmitOutcome.NOT_SENT, detail="ConnectError")
        if mode == "unknown_created":
            self._store(payload)  # Alpaca got it, but the response was lost
            return SubmitResult(SubmitOutcome.UNKNOWN, detail="ReadTimeout")
        if mode == "unknown_missing":
            return SubmitResult(SubmitOutcome.UNKNOWN, detail="ReadTimeout")
        raise RuntimeError("client blew up")

    def cancel_order(self, order_id):
        self._call("cancel_order")
        order = self.orders.get(order_id)
        if order is None or self.cancel_mode == "not_found":
            raise BrokerNotFound(order_id)
        if self.cancel_mode == "not_cancelable":
            raise BrokerConflict(422)
        if self.cancel_mode == "filled_race":
            order.update(status="filled", filled_qty=order.get("qty") or "1", filled_avg_price="101.00")
        else:
            order["status"] = "pending_cancel"


def make_service(tmp_path: Path, broker: FakeBroker | None = None, clock: Clock | None = None,
                 **setting_overrides) -> PaperTradingService:
    return PaperTradingService(settings(**setting_overrides), broker or FakeBroker(),
                               Repository(tmp_path / "paper.sqlite3"), now=clock or Clock())
