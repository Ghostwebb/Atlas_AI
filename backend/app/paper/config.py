"""Paper trading settings. Alpaca Paper only; there is no live code path.

The broker endpoint is a constant. It cannot be changed by configuration or by a
request. If the environment points anywhere else (for example the live API), the
server refuses to start. Secrets stay server-side and are never returned or logged.

The backend does not load .env files: export the variables in the shell that
starts uvicorn (see README).
"""

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_HOST = "api.alpaca.markets"

ENVIRONMENT = "paper"
ORDER_TYPE = "market"
TIME_IN_FORCE = "day"

# Amount policy (Alpaca accepts up to 9 decimals for qty and notional; ATLAS
# restricts notional to cents and enforces a $1 minimum for notional buys).
NOTIONAL_PATTERN = r"^\d{1,7}(\.\d{1,2})?$"
QTY_PATTERN = r"^\d{1,9}(\.\d{1,9})?$"
MIN_NOTIONAL_USD = Decimal("1.00")
MAX_ORDERS_PAGE = 100
DEFAULT_ORDERS_PAGE = 50

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "var" / "paper_trading.sqlite3"

# Variables that, if set, must point to the paper endpoint.
_URL_GUARD_VARIABLES = ("ATLAS_ALPACA_BASE_URL", "APCA_API_BASE_URL")


class PaperConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PaperSettings:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    max_order_notional: Decimal = Decimal("1000")
    proposal_ttl_seconds: int = 300
    database_path: Path = DEFAULT_DATABASE_PATH
    # Only for local tests with curl: accept mutating requests without an Origin header.
    allow_requests_without_origin: bool = False
    base_url: str = ALPACA_PAPER_BASE_URL  # fixed; validated below

    def __post_init__(self) -> None:
        errors: list[str] = []
        if self.base_url != ALPACA_PAPER_BASE_URL:
            errors.append("the Alpaca endpoint must be the paper endpoint")
        if self.api_key.upper().startswith("AK"):
            # Alpaca live key ids start with "AK"; paper key ids with "PK".
            errors.append("ATLAS_ALPACA_PAPER_API_KEY looks like a live key; only paper keys are accepted")
        if not (Decimal("1") <= self.max_order_notional <= Decimal("100000")):
            errors.append("ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD must be between 1 and 100000")
        if not 30 <= self.proposal_ttl_seconds <= 3600:
            errors.append("ATLAS_PAPER_PROPOSAL_TTL_SECONDS must be between 30 and 3600")
        if errors:
            raise PaperConfigError("; ".join(errors))

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip() and self.secret_key.strip())

    def __repr__(self) -> str:  # never print secrets
        return (f"PaperSettings(enabled={self.enabled}, configured={self.configured}, "
                f"max_order_notional={self.max_order_notional}, ttl={self.proposal_ttl_seconds})")


def _bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if raw == "":
        return default
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise PaperConfigError(f"{name} must be true or false")


def load_paper_settings(env: dict[str, str] | None = None) -> PaperSettings:
    env = dict(os.environ) if env is None else env

    for name in _URL_GUARD_VARIABLES:
        value = (env.get(name) or "").strip().rstrip("/")
        if value and value != ALPACA_PAPER_BASE_URL:
            raise PaperConfigError(f"{name} must be {ALPACA_PAPER_BASE_URL} (live trading is not supported)")

    raw_notional = (env.get("ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD") or "1000").strip()
    try:
        max_notional = Decimal(raw_notional)
    except InvalidOperation as error:
        raise PaperConfigError("ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD must be a number") from error
    if not max_notional.is_finite():
        raise PaperConfigError("ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD must be finite")

    raw_ttl = (env.get("ATLAS_PAPER_PROPOSAL_TTL_SECONDS") or "300").strip()
    try:
        ttl = int(raw_ttl)
    except ValueError as error:
        raise PaperConfigError("ATLAS_PAPER_PROPOSAL_TTL_SECONDS must be an integer") from error

    db = (env.get("ATLAS_PAPER_DATABASE_PATH") or "").strip()
    return PaperSettings(
        enabled=_bool(env, "ATLAS_PAPER_TRADING_ENABLED", False),
        api_key=(env.get("ATLAS_ALPACA_PAPER_API_KEY") or "").strip(),
        secret_key=(env.get("ATLAS_ALPACA_PAPER_SECRET_KEY") or "").strip(),
        max_order_notional=max_notional,
        proposal_ttl_seconds=ttl,
        database_path=Path(db) if db else DEFAULT_DATABASE_PATH,
        allow_requests_without_origin=_bool(env, "ATLAS_PAPER_ALLOW_REQUESTS_WITHOUT_ORIGIN", False),
    )
