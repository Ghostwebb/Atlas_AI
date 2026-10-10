"""In-memory fake of the Alpaca Paper client. No network. Records every call.

It behaves like a small broker so tests exercise the local limits, not the fake:
- open buy orders reduce non_marginable_buying_power by their remaining notional;
- open sell orders reduce qty_available by their remaining qty;
- fill() moves cash and positions; final fills close the order;
- freeze_account() / freeze_position() return stale snapshots on purpose.
It never rejects an order for lack of funds or shares (submit_mode decides),
so any over-commitment would be visible in `submits`.
"""

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.paper.client import BrokerConflict, BrokerNotFound, BrokerUnavailable, SubmitOutcome, SubmitResult
from app.paper.config import PaperSettings
from app.paper.repository import Repository
from app.paper.service import PaperTradingService

PAPER_KEY = "PKTESTKEY000000000000"
PAPER_SECRET = "test-secret-value-never-logged"
FINAL = {"filled", "canceled", "expired", "rejected"}


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


def D(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal(0)


class FakeBroker:
    def __init__(self):
        self.calls: list[str] = []
        self.submits: list[dict] = []
        # Base account values; non_marginable_buying_power is reduced dynamically by open buys.
        self.account = {"status": "ACTIVE", "currency": "USD", "trading_blocked": False,
                        "account_blocked": False, "cash": "100000", "buying_power": "200000",
                        "non_marginable_buying_power": "100000", "equity": "100000"}
        self.clock = {"is_open": True, "timestamp": "2026-10-05T11:00:00-04:00",
                      "next_open": "2026-10-06T09:30:00-04:00", "next_close": "2026-10-05T16:00:00-04:00"}
        self.assets = {
            "NVDA": {"symbol": "NVDA", "class": "us_equity", "status": "active", "tradable": True, "fractionable": True},
            "AAPL": {"symbol": "AAPL", "class": "us_equity", "status": "active", "tradable": True, "fractionable": True},
            "BRK.A": {"symbol": "BRK.A", "class": "us_equity", "status": "active", "tradable": True, "fractionable": False},
            "OLD": {"symbol": "OLD", "class": "us_equity", "status": "inactive", "tradable": False, "fractionable": False},
        }
        self.positions: dict[str, dict] = {}
        self._available_override: dict[str, str] = {}
        self.orders: dict[str, dict] = {}
        # submit behaviour: accept | reject | not_sent | unknown_created | unknown_missing | raise
        self.submit_mode = "accept"
        self.fill_status = "accepted"
        self.fill_qty = "0"
        self.submit_delay = 0.0
        self.cancel_mode = "pending_cancel"  # pending_cancel | filled_race | not_cancelable | not_found
        self.unavailable = False
        self.frozen_account: dict | None = None
        self.frozen_positions: dict[str, dict | None] = {}
        self._lock = threading.Lock()
        # Deterministic concurrency: {method_name: threading.Barrier}. Each call to that
        # method waits on the barrier after it is recorded (only while the entry exists).
        self.pause_after: dict[str, threading.Barrier] = {}

    def _call(self, name: str) -> None:
        with self._lock:
            self.calls.append(name)
        if self.unavailable:
            raise BrokerUnavailable("down")
        barrier = self.pause_after.get(name)
        if barrier is not None:
            barrier.wait(timeout=10)

    # --- state helpers used by tests ------------------------------------------

    def add_position(self, symbol: str, qty: str, qty_available: str | None = None, side: str = "long"):
        self.positions[symbol] = {"symbol": symbol, "side": side, "qty": qty,
                                  "avg_entry_price": "100", "market_value": "500", "asset_class": "us_equity"}
        if qty_available is not None:
            self._available_override[symbol] = qty_available

    def open_orders(self) -> list[dict]:
        return [o for o in self.orders.values() if o["status"] not in FINAL]

    def _open_buy_holds(self) -> Decimal:
        total = Decimal(0)
        for o in self.open_orders():
            if o["side"] == "buy" and o.get("notional"):
                cost = D(o["filled_qty"]) * D(o["filled_avg_price"]) if o.get("filled_avg_price") else Decimal(0)
                total += max(D(o["notional"]) - cost, Decimal(0))
        return total

    def _open_sell_remaining(self, symbol: str) -> Decimal:
        return sum((max(D(o["qty"]) - D(o["filled_qty"]), Decimal(0)) for o in self.open_orders()
                    if o["side"] == "sell" and o["symbol"] == symbol and o.get("qty")), Decimal(0))

    def freeze_account(self) -> None:
        """Return the current account values from now on, ignoring later orders (stale)."""
        self.frozen_account = self._live_account()

    def freeze_position(self, symbol: str) -> None:
        self.frozen_positions[symbol] = self._live_position(symbol)

    def place_external_order(self, **fields) -> dict:
        """An order created outside ATLAS (for example from the Alpaca dashboard)."""
        order = self._new_order({"client_order_id": f"external-{uuid.uuid4().hex[:8]}",
                                 "type": "market", "time_in_force": "day", **fields})
        order["status"] = "new"
        return order

    def fill(self, order_id: str, qty: str, price: str, final: bool) -> None:
        order = self.orders[order_id]
        qty_d, price_d = D(qty), D(price)
        previous = D(order["filled_qty"])
        previous_cost = previous * D(order["filled_avg_price"]) if order.get("filled_avg_price") else Decimal(0)
        order["filled_qty"] = str(previous + qty_d)
        # Volume-weighted average, as Alpaca reports filled_avg_price.
        order["filled_avg_price"] = str((previous_cost + qty_d * price_d) / (previous + qty_d))
        order["status"] = "filled" if final else "partially_filled"
        cost = qty_d * price_d
        pos = self.positions.setdefault(order["symbol"], {"symbol": order["symbol"], "side": "long", "qty": "0",
                                                         "avg_entry_price": price, "market_value": "0",
                                                         "asset_class": "us_equity"})
        if order["side"] == "buy":
            self.account["cash"] = str(D(self.account["cash"]) - cost)
            self.account["non_marginable_buying_power"] = str(D(self.account["non_marginable_buying_power"]) - cost)
            pos["qty"] = str(D(pos["qty"]) + qty_d)
        else:
            self.account["cash"] = str(D(self.account["cash"]) + cost)
            self.account["non_marginable_buying_power"] = str(D(self.account["non_marginable_buying_power"]) + cost)
            pos["qty"] = str(D(pos["qty"]) - qty_d)

    def finish_cancel(self, order_id: str) -> None:
        self.orders[order_id]["status"] = "canceled"

    def _live_account(self) -> dict:
        account = dict(self.account)
        if "non_marginable_buying_power" in account:
            account["non_marginable_buying_power"] = str(D(account["non_marginable_buying_power"]) - self._open_buy_holds())
        return account

    def _live_position(self, symbol: str) -> dict | None:
        base = self.positions.get(symbol)
        if base is None or D(base["qty"]) == 0:
            return None
        position = dict(base)
        if symbol in self._available_override:
            position["qty_available"] = self._available_override[symbol]
        else:
            position["qty_available"] = str(D(base["qty"]) - self._open_sell_remaining(symbol))
        return position

    # --- reads -------------------------------------------------------------------

    def get_account(self):
        self._call("get_account")
        return dict(self.frozen_account) if self.frozen_account is not None else self._live_account()

    def get_clock(self):
        self._call("get_clock")
        return dict(self.clock)

    def get_asset(self, symbol):
        self._call("get_asset")
        return self.assets.get(symbol)

    def get_position(self, symbol):
        self._call("get_position")
        if symbol in self.frozen_positions:
            frozen = self.frozen_positions[symbol]
            return dict(frozen) if frozen else None
        return self._live_position(symbol)

    def list_positions(self):
        self._call("list_positions")
        return [p for p in (self._live_position(s) for s in self.positions) if p]

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
        orders = list(self.orders.values())
        if status == "open":
            orders = [o for o in orders if o["status"] not in FINAL]
        elif status == "closed":
            orders = [o for o in orders if o["status"] in FINAL]
        return [dict(o) for o in orders[:limit]]

    # --- mutations ---------------------------------------------------------------

    def _new_order(self, payload: dict) -> dict:
        order = {"id": str(uuid.uuid4()), "client_order_id": payload["client_order_id"],
                 "symbol": payload["symbol"], "side": payload["side"], "type": payload.get("type", "market"),
                 "time_in_force": payload.get("time_in_force", "day"), "qty": payload.get("qty"),
                 "notional": payload.get("notional"), "filled_qty": "0", "filled_avg_price": None,
                 "status": "accepted", "submitted_at": "2026-10-05T15:00:01Z",
                 "filled_at": None, "canceled_at": None}
        self.orders[order["id"]] = order
        return order

    def _store(self, payload: dict) -> dict:
        order = self._new_order(payload)
        order["status"] = self.fill_status
        if self.fill_qty != "0":
            order["filled_qty"] = self.fill_qty
            order["filled_avg_price"] = "101.25"
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
        if self.cancel_mode == "not_cancelable" or order["status"] in FINAL:
            raise BrokerConflict(422)
        if self.cancel_mode == "filled_race":
            order.update(status="filled", filled_qty=order.get("qty") or "1", filled_avg_price="101.00")
        else:
            order["status"] = "pending_cancel"


def make_service(tmp_path: Path, broker: FakeBroker | None = None, clock: Clock | None = None,
                 **setting_overrides) -> PaperTradingService:
    return PaperTradingService(settings(**setting_overrides), broker or FakeBroker(),
                               Repository(tmp_path / "paper.sqlite3"), now=clock or Clock())
