"""Paper configuration guards and the Alpaca HTTP client (mocked transport only)."""

import json
import logging
from decimal import Decimal

import httpx
import pytest

from app.paper.client import AlpacaPaperClient, BrokerConflict, BrokerNotFound, BrokerUnavailable, SubmitOutcome
from app.paper.config import ALPACA_PAPER_BASE_URL, PaperConfigError, PaperSettings, load_paper_settings
from tests.paper_fakes import PAPER_KEY, PAPER_SECRET, settings

# --- 2. live configuration rejected / 3. secrets missing ------------------------


@pytest.mark.parametrize("name", ["APCA_API_BASE_URL", "ATLAS_ALPACA_BASE_URL"])
def test_live_endpoint_in_environment_is_rejected(name):
    with pytest.raises(PaperConfigError, match="live trading is not supported"):
        load_paper_settings({name: "https://api.alpaca.markets"})


def test_paper_endpoint_in_environment_is_accepted():
    assert load_paper_settings({"APCA_API_BASE_URL": ALPACA_PAPER_BASE_URL + "/"}).enabled is False


def test_base_url_cannot_be_changed_in_settings():
    with pytest.raises(PaperConfigError):
        PaperSettings(base_url="https://api.alpaca.markets")


def test_live_looking_key_is_rejected():
    with pytest.raises(PaperConfigError, match="live key"):
        load_paper_settings({"ATLAS_ALPACA_PAPER_API_KEY": "AKLIVEKEY"})


def test_defaults_are_disabled_and_unconfigured():
    s = load_paper_settings({})
    assert (s.enabled, s.configured, s.max_order_notional, s.proposal_ttl_seconds) == (False, False, Decimal("1000"), 300)


def test_enabled_without_secrets_is_not_configured():
    s = load_paper_settings({"ATLAS_PAPER_TRADING_ENABLED": "true", "ATLAS_ALPACA_PAPER_API_KEY": PAPER_KEY})
    assert s.enabled and not s.configured


@pytest.mark.parametrize("env", [
    {"ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD": "abc"},
    {"ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD": "NaN"},
    {"ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD": "0"},
    {"ATLAS_PAPER_PROPOSAL_TTL_SECONDS": "5"},
    {"ATLAS_PAPER_PROPOSAL_TTL_SECONDS": "1.5"},
    {"ATLAS_PAPER_TRADING_ENABLED": "maybe"},
])
def test_invalid_settings_are_rejected(env):
    with pytest.raises(PaperConfigError):
        load_paper_settings(env)


def test_secrets_never_in_repr():
    text = repr(settings())
    assert PAPER_SECRET not in text and PAPER_KEY not in text


# --- HTTP client --------------------------------------------------------------

def _client(handler) -> AlpacaPaperClient:
    return AlpacaPaperClient(settings(), transport=httpx.MockTransport(handler))


def test_reads_use_paper_host_and_auth_headers():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"is_open": True})

    _client(handler).get_clock()
    request = seen[0]
    assert str(request.url) == "https://paper-api.alpaca.markets/v2/clock"
    assert request.headers["APCA-API-KEY-ID"] == PAPER_KEY
    assert request.headers["APCA-API-SECRET-KEY"] == PAPER_SECRET


def test_lookup_by_client_order_id_path():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(404, json={"message": "not found"})

    assert _client(handler).get_order_by_client_id("atlas-abc") is None
    assert seen[0].url.path == "/v2/orders:by_client_order_id"
    assert seen[0].url.params["client_order_id"] == "atlas-abc"


@pytest.mark.parametrize(("make", "outcome"), [
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")), SubmitOutcome.NOT_SENT),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("slow")), SubmitOutcome.NOT_SENT),
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), SubmitOutcome.UNKNOWN),
    (lambda r: (_ for _ in ()).throw(httpx.WriteTimeout("slow")), SubmitOutcome.UNKNOWN),
    (lambda r: (_ for _ in ()).throw(httpx.RemoteProtocolError("closed")), SubmitOutcome.UNKNOWN),
    (lambda r: httpx.Response(500, text="boom"), SubmitOutcome.UNKNOWN),
    (lambda r: httpx.Response(429, text="slow down"), SubmitOutcome.UNKNOWN),
    (lambda r: httpx.Response(200, text="not json"), SubmitOutcome.UNKNOWN),
    (lambda r: httpx.Response(403, json={"message": "insufficient buying power"}), SubmitOutcome.REJECTED),
    (lambda r: httpx.Response(422, json={"message": "invalid"}), SubmitOutcome.REJECTED),
    (lambda r: httpx.Response(200, json={"id": "o1", "status": "accepted"}), SubmitOutcome.ACCEPTED),
])
def test_submit_outcomes_are_classified(make, outcome):
    assert _client(make).submit_order({"symbol": "NVDA"}).outcome is outcome


def test_submit_sends_exact_payload_once():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(500)

    payload = {"symbol": "NVDA", "side": "buy", "type": "market", "time_in_force": "day",
               "notional": "100.00", "client_order_id": "atlas-x"}
    _client(handler).submit_order(payload)
    assert len(seen) == 1  # no retry, even on 5xx
    assert seen[0].method == "POST" and seen[0].url.path == "/v2/orders"
    assert json.loads(seen[0].content) == payload


def test_cancel_mapping():
    assert _client(lambda r: httpx.Response(204)).cancel_order("o1") is None
    with pytest.raises(BrokerConflict):
        _client(lambda r: httpx.Response(422, json={"message": "not cancelable"})).cancel_order("o1")
    with pytest.raises(BrokerNotFound):
        _client(lambda r: httpx.Response(404)).cancel_order("o1")
    with pytest.raises(BrokerUnavailable):
        _client(lambda r: httpx.Response(503)).cancel_order("o1")


def test_read_errors_do_not_log_secrets_or_bodies(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(BrokerUnavailable) as excinfo:
        _client(lambda r: httpx.Response(401, text=f"bad key {PAPER_KEY}")).get_account()
    assert PAPER_KEY not in str(excinfo.value)
    assert PAPER_SECRET not in caplog.text and PAPER_KEY not in caplog.text
