"""Evaluate every registered strategy on ONE shared snapshot of a symbol.

The provider is queried once per request; strategies never fetch data themselves. No model
(Gemma) and no broker (Alpaca) is called, and nothing here creates proposals or orders.
"""

from app.agents.config import SCHEMA_VERSION
from app.agents.engine import evaluate, validate_references
from app.agents.models import AgentsAnalyzeResponse
from app.agents.snapshot import AgentSnapshot, build_agent_snapshot
from app.agents.strategies import REGISTRY
from app.data.provider import MarketDataProvider

NOTICE = ("Strategy evaluations on a synthetic demo dataset. They are explicit rules, not predictions, "
          "not recommendations and not orders. No agent selects a winner or trades.")
GLOBAL_LIMITATIONS = [
    "Each agent evaluates the same snapshot independently; there is no committee decision in this phase.",
    "Stances describe the evidence through each strategy's lens; agents can legitimately disagree.",
    "Thresholds are documented heuristics, not calibrated against real outcomes.",
    "coverage measures only the scored criteria; risk checks that could not run are listed in risksNotEvaluated.",
]


def _snapshot_json(s: AgentSnapshot) -> dict:
    return {
        "symbol": s.symbol, "companyName": s.company_name, "dataSource": s.data_source,
        "provenance": s.provenance, "isSimulated": s.is_simulated, "observations": s.observations,
        "firstDate": s.first_date, "lastDate": s.last_date, "dataIssues": list(s.data_issues),
        "warnings": list(s.warnings),
        "metrics": {key: {"value": m.value, "status": m.status, "issue": m.issue, "unit": m.unit, "source": m.source,
                          "window": m.window, "description": m.description} for key, m in s.metrics.items()},
    }


def evaluate_snapshot(snapshot: AgentSnapshot) -> AgentsAnalyzeResponse:
    document = {
        "schemaVersion": SCHEMA_VERSION,
        "notice": NOTICE if snapshot.is_simulated else NOTICE.replace("on a synthetic demo dataset", "on the snapshot"),
        "snapshot": _snapshot_json(snapshot),
        "evaluations": [evaluate(strategy, snapshot) for strategy in REGISTRY],
        "limitations": list(GLOBAL_LIMITATIONS),
    }
    validate_references(document)
    return AgentsAnalyzeResponse.model_validate(document)


def analyze_agents(symbol: str, provider: MarketDataProvider) -> AgentsAnalyzeResponse | None:
    market = provider.get_snapshot(symbol)
    if market is None:
        return None
    return evaluate_snapshot(build_agent_snapshot(market))
