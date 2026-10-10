"""Committee orchestration: ONE agents evaluation (one provider query) -> committee -> integrity check.

No model (Gemma), no broker (Alpaca), no proposals or orders. Agent evaluations are never modified.
"""

from app.agents.service import analyze_agents
from app.committee import config as C
from app.committee.integrity import CommitteeIntegrityError, validate_committee
from app.committee.models import CommitteeAnalyzeResponse
from app.committee.rules import build_committee
from app.data.provider import MarketDataProvider

NOTICE = ("Deterministic committee reading of four strategy evaluations on one synthetic snapshot. It compares "
          "perspectives; it does not invest, does not authorize or place operations, does not pick a winning agent "
          "and does not predict returns.")


def committee_from_agents(agents: dict) -> CommitteeAnalyzeResponse:
    if agents.get("schemaVersion") != C.AGENTS_SCHEMA_VERSION:
        raise CommitteeIntegrityError(f"unsupported agents schema {agents.get('schemaVersion')}")
    document = {"schemaVersion": C.SCHEMA_VERSION, "policyVersion": C.POLICY_VERSION, "notice": NOTICE,
                "agents": agents, "committee": build_committee(agents)}
    validate_committee(document)
    return CommitteeAnalyzeResponse.model_validate(document)


def analyze_committee(symbol: str, provider: MarketDataProvider) -> CommitteeAnalyzeResponse | None:
    agents = analyze_agents(symbol, provider)
    if agents is None:
        return None
    return committee_from_agents(agents.model_dump(mode="json"))
