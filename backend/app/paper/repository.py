"""SQLite persistence for proposals, reservations and audit events (standard library only).

Integrity is enforced by the database, not by in-memory locks:
- proposals.client_order_id and proposals.broker_order_id are UNIQUE;
- a partial UNIQUE index allows at most one active reservation per proposal;
- every state change is a conditional UPDATE inside a BEGIN IMMEDIATE
  transaction. BEGIN IMMEDIATE takes SQLite's write lock, so confirmations from
  different threads, repository instances or processes on the same file are
  serialized. The capacity re-check, the reservation insert, the proposal
  transition and the intent event commit together or not at all.
No transaction is ever held open across an HTTP call.

Amounts are decimal strings. They are summed in Python with Decimal, never as
SQLite REAL.

Schema versions (PRAGMA user_version):
  0/1  Phase 5: proposals, events
  2    Phase 5.5: reservations table, submit lease columns, conservative backfill
"""

import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator

SCHEMA_VERSION = 2

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS proposals (
    id                TEXT PRIMARY KEY,
    client_order_id   TEXT NOT NULL UNIQUE,
    environment       TEXT NOT NULL CHECK (environment = 'paper'),
    symbol            TEXT NOT NULL,
    side              TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    notional          TEXT,
    qty               TEXT,
    order_type        TEXT NOT NULL,
    time_in_force     TEXT NOT NULL,
    analysis_reference TEXT,
    created_at        TEXT NOT NULL,
    expires_at        TEXT NOT NULL,
    status            TEXT NOT NULL,
    submission_status TEXT NOT NULL,
    broker_order_id   TEXT UNIQUE,
    broker_status     TEXT,
    filled_qty        TEXT,
    filled_avg_price  TEXT,
    last_error_code   TEXT,
    checks            TEXT NOT NULL,
    warnings          TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    version           INTEGER NOT NULL DEFAULT 0,
    CHECK ((side = 'buy' AND notional IS NOT NULL AND qty IS NULL)
        OR (side = 'sell' AND qty IS NOT NULL AND notional IS NULL))
);
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id    TEXT,
    at             TEXT NOT NULL,
    type           TEXT NOT NULL,
    correlation_id TEXT,
    data           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_proposal ON events (proposal_id);
CREATE INDEX IF NOT EXISTS proposals_submission ON proposals (submission_status);
"""

MIGRATION_V2 = """
ALTER TABLE proposals ADD COLUMN submit_owner TEXT;
ALTER TABLE proposals ADD COLUMN submit_lease_until TEXT;
CREATE TABLE reservations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id     TEXT NOT NULL REFERENCES proposals (id),
    resource_type   TEXT NOT NULL CHECK (resource_type IN ('cash', 'shares')),
    symbol          TEXT,
    amount          TEXT NOT NULL,
    consumed        TEXT NOT NULL DEFAULT '0',
    state           TEXT NOT NULL CHECK (state IN ('held', 'acknowledged', 'released')),
    release_reason  TEXT,
    broker_order_id TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    CHECK (resource_type = 'cash' OR symbol IS NOT NULL),
    CHECK ((state = 'released') = (release_reason IS NOT NULL))
);
CREATE UNIQUE INDEX reservations_one_active ON reservations (proposal_id)
    WHERE state IN ('held', 'acknowledged');
CREATE INDEX reservations_resource ON reservations (resource_type, symbol, state);
"""

ACTIVE_STATES = ("held", "acknowledged")
TERMINAL = {"filled", "canceled", "expired", "rejected"}

PROPOSAL_FIELDS = (
    "id", "client_order_id", "environment", "symbol", "side", "notional", "qty", "order_type",
    "time_in_force", "analysis_reference", "created_at", "expires_at", "status",
    "submission_status", "broker_order_id", "broker_status", "filled_qty", "filled_avg_price",
    "last_error_code", "checks", "warnings", "updated_at", "version",
)
# Fields that may change after creation. Symbol, side, amounts and ids never change.
MUTABLE_FIELDS = {
    "status", "submission_status", "broker_order_id", "broker_status", "filled_qty",
    "filled_avg_price", "last_error_code", "updated_at", "submit_owner", "submit_lease_until",
}
RESERVATION_MUTABLE = {"state", "release_reason", "broker_order_id", "consumed", "updated_at"}


def consumed_amount(side: str, filled_qty: Any, filled_avg_price: Any) -> Decimal:
    """Shares filled for a sell; filled cost (qty x avg price) for a buy. Decimal only."""
    try:
        qty = Decimal(str(filled_qty)) if filled_qty not in (None, "") else Decimal(0)
        price = Decimal(str(filled_avg_price)) if filled_avg_price not in (None, "") else None
    except ArithmeticError:
        return Decimal(0)
    if side == "sell":
        return qty
    return qty * price if price is not None else Decimal(0)


class Repository:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # --- migration ----------------------------------------------------------

    def _migrate(self) -> None:
        # Statements run one by one inside a single transaction (executescript would
        # commit implicitly). A failed migration leaves the file unchanged.
        with self.transaction() as conn:
            for statement in SCHEMA_V1.split(";"):
                if statement.strip():
                    conn.execute(statement)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < 2:
                for statement in MIGRATION_V2.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                self._backfill_reservations(conn)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _backfill_reservations(conn: sqlite3.Connection) -> None:
        """Phase 5 rows get conservative protection: anything that may hold money or
        shares at Alpaca keeps an active reservation until it is reconciled."""
        rows = conn.execute(
            "SELECT * FROM proposals WHERE submission_status IN ('submitting', 'submission_unknown', 'submitted')"
        ).fetchall()
        for row in rows:
            if row["submission_status"] == "submitted" and (row["broker_status"] or "") in TERMINAL:
                continue
            state = "acknowledged" if row["submission_status"] == "submitted" else "held"
            consumed = consumed_amount(row["side"], row["filled_qty"], row["filled_avg_price"])
            conn.execute(
                "INSERT INTO reservations (proposal_id, resource_type, symbol, amount, consumed, state, "
                "broker_order_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["id"], "cash" if row["side"] == "buy" else "shares",
                 row["symbol"] if row["side"] == "sell" else None,
                 row["notional"] if row["side"] == "buy" else row["qty"], str(consumed), state,
                 row["broker_order_id"], row["updated_at"], row["updated_at"]),
            )
            Repository._event(conn, {"proposal_id": row["id"], "at": row["updated_at"],
                                     "type": "reservation_backfilled", "data": {"state": state}})

    # --- proposals -------------------------------------------------------

    def insert_proposal(self, row: dict[str, Any], event: dict[str, Any]) -> None:
        values = {**row, "checks": json.dumps(row["checks"]), "warnings": json.dumps(row["warnings"])}
        with self.transaction() as conn:
            conn.execute(
                f"INSERT INTO proposals ({', '.join(PROPOSAL_FIELDS)}) "
                f"VALUES ({', '.join('?' for _ in PROPOSAL_FIELDS)})",
                [values[f] for f in PROPOSAL_FIELDS],
            )
            self._event(conn, event)

    def _one(self, sql: str, params: tuple) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._decode(conn.execute(sql, params).fetchone())

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM proposals WHERE id = ?", (proposal_id,))

    def get_by_client_order_id(self, client_order_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM proposals WHERE client_order_id = ?", (client_order_id,))

    def get_by_broker_order_id(self, order_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM proposals WHERE broker_order_id = ?", (order_id,))

    def list_by_submission(self, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
        marks = ", ".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM proposals WHERE submission_status IN ({marks}) ORDER BY created_at",
                statuses,
            ).fetchall()
        return [self._decode(r) for r in rows]

    # --- reservations ---------------------------------------------------------

    _ACTIVE_SQL = (
        "SELECT r.*, p.client_order_id, p.submission_status, p.submit_lease_until, p.side "
        "FROM reservations r JOIN proposals p ON p.id = r.proposal_id "
        "WHERE r.state IN ('held', 'acknowledged') AND r.resource_type = ? "
        "AND (? IS NULL OR r.symbol = ?) ORDER BY r.id"
    )

    def active_reservations(self, resource_type: str, symbol: str | None,
                            conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        params = (resource_type, symbol, symbol)
        if conn is not None:
            return [dict(r) for r in conn.execute(self._ACTIVE_SQL, params).fetchall()]
        with self._connect() as own:
            return [dict(r) for r in own.execute(self._ACTIVE_SQL, params).fetchall()]

    def all_active_reservations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT r.*, p.client_order_id, p.submission_status FROM reservations r "
                "JOIN proposals p ON p.id = r.proposal_id WHERE r.state IN ('held', 'acknowledged')"
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_reservation(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reservations WHERE proposal_id = ? ORDER BY id DESC LIMIT 1",
                               (proposal_id,)).fetchone()
        return dict(row) if row else None

    def reservations_of(self, proposal_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM reservations WHERE proposal_id = ? ORDER BY id",
                                (proposal_id,)).fetchall()
        return [dict(r) for r in rows]

    # --- atomic operations -------------------------------------------------------

    @staticmethod
    def _update_proposal(conn, proposal_id, expected, changes, extra_where, extra_params) -> bool:
        if not set(changes) <= MUTABLE_FIELDS:
            raise ValueError(f"immutable fields: {set(changes) - MUTABLE_FIELDS}")
        where, params = ["id = ?"], [proposal_id]
        for column, allowed in expected.items():
            where.append(f"{column} IN ({', '.join('?' for _ in allowed)})")
            params.extend(allowed)
        if extra_where:
            where.append(extra_where)
            params.extend(extra_params)
        sets = ", ".join(f"{c} = ?" for c in changes) + ", version = version + 1"
        cursor = conn.execute(f"UPDATE proposals SET {sets} WHERE {' AND '.join(where)}",
                              [*changes.values(), *params])
        return cursor.rowcount == 1

    def claim(self, proposal_id: str, expected: dict[str, tuple[str, ...]], changes: dict[str, Any],
              reservation: dict[str, Any], event: dict[str, Any],
              check: Callable[[list[dict[str, Any]]], None],
              extra_where: str = "", extra_params: tuple = ()) -> bool:
        """Atomically: proposal transition + capacity re-check + reservation + intent event.

        `check` receives the active reservations of the same resource, read inside
        this write transaction, and raises to abort (everything is rolled back).
        Returns False if the proposal was not in the expected state.
        """
        with self.transaction() as conn:
            if not self._update_proposal(conn, proposal_id, expected, changes, extra_where, extra_params):
                return False
            check(self.active_reservations(reservation["resource_type"], reservation["symbol"], conn))
            conn.execute(
                "INSERT INTO reservations (proposal_id, resource_type, symbol, amount, consumed, state, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, '0', 'held', ?, ?)",
                (proposal_id, reservation["resource_type"], reservation["symbol"], reservation["amount"],
                 reservation["created_at"], reservation["created_at"]),
            )
            self._event(conn, event)
            return True

    def transition(self, proposal_id: str, expected: dict[str, tuple[str, ...]],
                   changes: dict[str, Any], event: dict[str, Any], extra_where: str = "",
                   extra_params: tuple = (), reservation_changes: dict[str, Any] | None = None) -> bool:
        """Apply `changes` (and optionally update the proposal's active reservation)
        only if the current row matches `expected`. Returns True if applied."""
        if reservation_changes and not set(reservation_changes) <= RESERVATION_MUTABLE:
            raise ValueError(f"immutable reservation fields: {set(reservation_changes) - RESERVATION_MUTABLE}")
        with self.transaction() as conn:
            if not self._update_proposal(conn, proposal_id, expected, changes, extra_where, extra_params):
                return False
            if reservation_changes:
                sets = ", ".join(f"{c} = ?" for c in reservation_changes)
                conn.execute(
                    f"UPDATE reservations SET {sets} WHERE proposal_id = ? AND state IN ('held', 'acknowledged')",
                    [*reservation_changes.values(), proposal_id],
                )
            self._event(conn, event)
            return True

    # --- events ---------------------------------------------------------------

    def add_event(self, event: dict[str, Any]) -> None:
        with self.transaction() as conn:
            self._event(conn, event)

    def events(self, proposal_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM events WHERE proposal_id = ? ORDER BY id",
                                (proposal_id,)).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    @staticmethod
    def _event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO events (proposal_id, at, type, correlation_id, data) VALUES (?, ?, ?, ?, ?)",
            (event.get("proposal_id"), event["at"], event["type"], event.get("correlation_id"),
             json.dumps(event.get("data", {}), sort_keys=True)),
        )

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["checks"] = json.loads(data["checks"])
        data["warnings"] = json.loads(data["warnings"])
        return data
