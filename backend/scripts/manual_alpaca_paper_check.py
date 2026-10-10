"""Manual check against a real Alpaca PAPER account. Not part of pytest or CI.

Default mode is READ-ONLY: connection, account, market clock, one asset and
positions. Nothing is submitted.

    cd backend
    export ATLAS_PAPER_TRADING_ENABLED=true
    export ATLAS_ALPACA_PAPER_API_KEY=...       # paper key id (starts with PK)
    export ATLAS_ALPACA_PAPER_SECRET_KEY=...
    ./.venv/bin/python scripts/manual_alpaca_paper_check.py NVDA

Optional order test (paper money only), requires an explicit flag AND typing a
confirmation phrase that repeats symbol, amount and environment:

    ./.venv/bin/python scripts/manual_alpaca_paper_check.py NVDA --submit-buy 5.00

The order goes through the same service as the API (validation, persisted
proposal, single submit, reconciliation). Its result is read back from Alpaca;
an HTTP acceptance alone is never reported as an execution.
"""

import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.paper.client import AlpacaPaperClient, BrokerUnavailable  # noqa: E402
from app.paper.config import ALPACA_PAPER_BASE_URL, load_paper_settings  # noqa: E402
from app.paper.models import PaperError, ProposalRequest  # noqa: E402
from app.paper.repository import Repository  # noqa: E402
from app.paper.service import PaperTradingService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", nargs="?", default="NVDA")
    parser.add_argument("--submit-buy", metavar="USD", help="submit one notional paper buy after confirmation")
    args = parser.parse_args()
    symbol = args.symbol.upper()

    settings = load_paper_settings()
    if not settings.enabled or not settings.configured:
        print("Set ATLAS_PAPER_TRADING_ENABLED=true and the paper key id/secret first.")
        return 2
    print(f"Environment: PAPER ({ALPACA_PAPER_BASE_URL})")

    client = AlpacaPaperClient(settings)
    try:
        try:
            account = client.get_account()
            clock = client.get_clock()
            asset = client.get_asset(symbol)
            positions = client.list_positions()
        except BrokerUnavailable as error:
            print(f"Alpaca Paper not reachable or credentials rejected: {error}")
            return 1
        print(f"Account: status={account.get('status')} trading_blocked={account.get('trading_blocked')} "
              f"buying_power={account.get('buying_power')} "
              f"non_marginable_buying_power={account.get('non_marginable_buying_power')}")
        print(f"Market: is_open={clock.get('is_open')} next_open={clock.get('next_open')} "
              f"next_close={clock.get('next_close')}")
        print(f"Asset {symbol}: " + ("not found" if asset is None else
              f"class={asset.get('class')} status={asset.get('status')} tradable={asset.get('tradable')} "
              f"fractionable={asset.get('fractionable')}"))
        print(f"Positions: {[(p.get('symbol'), p.get('qty'), p.get('qty_available')) for p in positions]}")

        if not args.submit_buy:
            print("Read-only check finished. No order was sent.")
            return 0

        phrase = f"PAPER BUY {symbol} {args.submit_buy} USD"
        print(f"\nAbout to send a PAPER market buy: {symbol}, notional {args.submit_buy} USD, "
              "time_in_force=day. Simulated money only.")
        if input(f'Type exactly "{phrase}" to continue: ').strip() != phrase:
            print("Confirmation did not match. Nothing was sent.")
            return 1

        db = Path(__file__).with_name("manual_alpaca_paper.sqlite3")
        service = PaperTradingService(settings, client, Repository(db))
        cid = uuid.uuid4().hex
        try:
            proposal = service.create_proposal(
                ProposalRequest(symbol=symbol, side="buy", notional=args.submit_buy), cid)
            print(f"Proposal {proposal.id} client_order_id={proposal.clientOrderId}")
            proposal = service.confirm(proposal.id, cid)
        except PaperError as error:
            print(f"Not submitted or uncertain: {error.code.value}: {error.message}")
            return 1
        print(f"Submitted: broker order {proposal.brokerOrderId}, status {proposal.brokerStatus.value}")
        for _ in range(5):  # read back the real broker status
            time.sleep(2)
            order = service.get_order(proposal.brokerOrderId, cid)
            print(f"Broker status: {order.status.value} filled_qty={order.filledQty} avg={order.filledAvgPrice}")
            if order.status.value in ("filled", "canceled", "expired", "rejected"):
                break
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
