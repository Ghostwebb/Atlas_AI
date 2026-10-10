"""SQLite persistence for proposals and audit events (standard library only).

Integrity is enforced by the database, not by in-memory locks:
- proposals.client_order_id and proposals.broker_order_id are UNIQUE;
- state transitions are conditional UPDATEs inside BEGIN IMMEDIATE
  transactions, so only one confirmation can claim a proposal.
Each operation opens its own connection, so the repository is safe to use from
FastAPI's thread pool.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
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

PROPOSAL_FIELDS = (
    "id", "client_order_id", "environment", "symbol", "side", "notional", "qty", "order_type",
    "time_in_force", "analysis_reference", "created_at", "expires_at", "status",
    "submission_status", "broker_order_id", "broker_status", "filled_qty", "filled_avg_price",
    "last_error_code", "checks", "warnings", "updated_at", "version",
)
# Fields that may change after creation. Symbol, side, amounts and ids never change.
MUTABLE_FIELDS = {
    "status", "submission_status", "broker_order_id", "broker_status", "filled_qty",
    "filled_avg_price", "last_error_code", "updated_at",
}


class Repository:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
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

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return self._decode(row)

    def get_by_client_order_id(self, client_order_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proposals WHERE client_order_id = ?",
                               (client_order_id,)).fetchone()
        return self._decode(row)

    def get_by_broker_order_id(self, order_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proposals WHERE broker_order_id = ?", (order_id,)).fetchone()
        return self._decode(row)

    def list_by_submission(self, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
        marks = ", ".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM proposals WHERE submission_status IN ({marks}) ORDER BY created_at",
                statuses,
            ).fetchall()
        return [self._decode(r) for r in rows]

    def committed_sell_qty(self, symbol: str, exclude_id: str | None = None) -> list[str]:
        """qty strings of local sells whose broker outcome is still unknown."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT qty FROM proposals WHERE symbol = ? AND side = 'sell' "
                "AND submission_status IN ('submitting', 'submission_unknown') AND id IS NOT ?",
                (symbol, exclude_id),
            ).fetchall()
        return [r["qty"] for r in rows]

    def transition(self, proposal_id: str, expected: dict[str, tuple[str, ...]],
                   changes: dict[str, Any], event: dict[str, Any], extra_where: str = "",
                   extra_params: tuple = ()) -> bool:
        """Apply `changes` only if the current row matches `expected`. Returns True if applied."""
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
        with self.transaction() as conn:
            cursor = conn.execute(f"UPDATE proposals SET {sets} WHERE {' AND '.join(where)}",
                                  [*changes.values(), *params])
            if cursor.rowcount != 1:
                return False
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
