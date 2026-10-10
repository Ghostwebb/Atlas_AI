"""Alpaca Paper Trading HTTP client (paper endpoint only).

Endpoints (Alpaca Trading API v2, verified against docs.alpaca.markets):
  GET    /v2/account, /v2/clock, /v2/assets/{symbol}, /v2/positions, /v2/positions/{symbol}
  POST   /v2/orders
  GET    /v2/orders, /v2/orders/{id}, /v2/orders:by_client_order_id?client_order_id=...
  DELETE /v2/orders/{id}   (204 = cancel request accepted, 422 = not cancelable)
Auth headers: APCA-API-KEY-ID / APCA-API-SECRET-KEY.

No retries on any call. Submission outcomes are classified explicitly:
  NOT_SENT  connection never established (ConnectError / ConnectTimeout)
  UNKNOWN   request may have reached Alpaca (read/write timeout, broken
            connection, 5xx, unreadable body)
  REJECTED  explicit 4xx answer
  ACCEPTED  200 with an order body
Broker bodies are never returned to API clients; only sanitized summaries are logged.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

import httpx

from app.paper.config import ALPACA_PAPER_BASE_URL, PaperSettings

logger = logging.getLogger("atlas.paper.client")


class BrokerUnavailable(Exception):
    """A read call failed (network, timeout, 5xx, auth, malformed body)."""


class BrokerNotFound(Exception):
    pass


class BrokerConflict(Exception):
    """4xx on a non-submit call (for example 422 when canceling)."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class SubmitOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SubmitResult:
    outcome: SubmitOutcome
    order: dict[str, Any] | None = None
    http_status: int | None = None
    detail: str = ""  # sanitized, internal only


class BrokerClient(Protocol):
    def get_account(self) -> dict[str, Any]: ...
    def get_clock(self) -> dict[str, Any]: ...
    def get_asset(self, symbol: str) -> dict[str, Any] | None: ...
    def get_position(self, symbol: str) -> dict[str, Any] | None: ...
    def list_positions(self) -> list[dict[str, Any]]: ...
    def submit_order(self, payload: dict[str, Any]) -> SubmitResult: ...
    def get_order(self, order_id: str) -> dict[str, Any] | None: ...
    def get_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None: ...
    def list_orders(self, status: str, limit: int) -> list[dict[str, Any]]: ...
    def cancel_order(self, order_id: str) -> None: ...


class AlpacaPaperClient:
    def __init__(self, settings: PaperSettings, transport: httpx.BaseTransport | None = None,
                 timeout_seconds: float = 10.0):
        if settings.base_url != ALPACA_PAPER_BASE_URL:
            raise ValueError("paper endpoint required")
        self._http = httpx.Client(
            base_url=ALPACA_PAPER_BASE_URL,
            headers={
                "APCA-API-KEY-ID": settings.api_key,
                "APCA-API-SECRET-KEY": settings.secret_key,
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )

    # --- reads -----------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None, not_found_ok: bool = False):
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as error:
            logger.warning("alpaca read failed path=%s error=%s", path, type(error).__name__)
            raise BrokerUnavailable(type(error).__name__) from error
        if response.status_code == 404 and not_found_ok:
            return None
        if response.status_code != 200:
            logger.warning("alpaca read status path=%s status=%s", path, response.status_code)
            raise BrokerUnavailable(f"HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as error:
            raise BrokerUnavailable("malformed body") from error

    def get_account(self) -> dict[str, Any]:
        return self._get("/v2/account")

    def get_clock(self) -> dict[str, Any]:
        return self._get("/v2/clock")

    def get_asset(self, symbol: str) -> dict[str, Any] | None:
        return self._get(f"/v2/assets/{symbol}", not_found_ok=True)

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        return self._get(f"/v2/positions/{symbol}", not_found_ok=True)

    def list_positions(self) -> list[dict[str, Any]]:
        return self._get("/v2/positions")

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        return self._get(f"/v2/orders/{order_id}", not_found_ok=True)

    def get_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        return self._get("/v2/orders:by_client_order_id",
                         params={"client_order_id": client_order_id}, not_found_ok=True)

    def list_orders(self, status: str, limit: int) -> list[dict[str, Any]]:
        return self._get("/v2/orders", params={"status": status, "limit": limit, "direction": "desc"})

    # --- mutations (never retried) ------------------------------------------

    def submit_order(self, payload: dict[str, Any]) -> SubmitResult:
        try:
            response = self._http.post("/v2/orders", json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            return SubmitResult(SubmitOutcome.NOT_SENT, detail=type(error).__name__)
        except httpx.HTTPError as error:
            # Read/write timeouts and broken connections: the order may exist.
            return SubmitResult(SubmitOutcome.UNKNOWN, detail=type(error).__name__)

        status = response.status_code
        if status == 200:
            try:
                order = response.json()
                order["id"], order["status"]
            except (ValueError, KeyError, TypeError):
                return SubmitResult(SubmitOutcome.UNKNOWN, http_status=status, detail="unreadable body")
            return SubmitResult(SubmitOutcome.ACCEPTED, order=order, http_status=status)
        if 400 <= status < 500 and status not in (408, 429):
            return SubmitResult(SubmitOutcome.REJECTED, http_status=status, detail=f"HTTP {status}")
        # 408/429/5xx: the request reached the server; the order may or may not exist.
        return SubmitResult(SubmitOutcome.UNKNOWN, http_status=status, detail=f"HTTP {status}")

    def cancel_order(self, order_id: str) -> None:
        try:
            response = self._http.delete(f"/v2/orders/{order_id}")
        except httpx.HTTPError as error:
            raise BrokerUnavailable(type(error).__name__) from error
        if response.status_code in (200, 204):
            return
        if response.status_code == 404:
            raise BrokerNotFound(order_id)
        if 400 <= response.status_code < 500:
            raise BrokerConflict(response.status_code)
        raise BrokerUnavailable(f"HTTP {response.status_code}")

    def close(self) -> None:
        self._http.close()
