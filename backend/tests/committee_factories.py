"""Controlled, validated agents evaluations for committee tests.

Evaluations are produced by the real Phase 7 engine from controlled snapshots, so they are coherent
and pass the agents reference validation. Synthetic, test-only data.
"""

import copy

from app.agents.service import evaluate_snapshot
from app.committee.rules import build_committee
from app.committee.service import committee_from_agents
from tests.agents_factories import agent_snapshot

# Every perspective evaluable; NOVA and VECTOR favorable on distinct core metrics; ARGO neutral (P/E 20);
# AEGIS complete and favorable; no risk flag fires and every risk check can run.
FAVORABLE = dict(
    revenue_growth=0.20, earnings_growth=0.20, profit_margin=0.20, pe_ratio=20.0,
    return_60d=0.20, return_20d=0.05, price_vs_sma20=0.02, sma20_vs_sma50=0.03, volume_ratio_20_60=1.0,
    volatility_annualized=0.20, volatility_20d=0.20, max_drawdown=0.10, current_drawdown=0.02,
)
UNFAVORABLE = dict(
    revenue_growth=0.0, earnings_growth=-0.10, profit_margin=0.02, pe_ratio=20.0,
    return_60d=-0.20, return_20d=-0.05, price_vs_sma20=-0.02, sma20_vs_sma50=-0.03, volume_ratio_20_60=1.0,
    volatility_annualized=0.30, volatility_20d=0.30, max_drawdown=0.20, current_drawdown=0.10,
)


def agents_doc(**metrics) -> dict:
    return evaluate_snapshot(agent_snapshot(**metrics)).model_dump(mode="json")


def committee(**metrics) -> dict:
    return build_committee(agents_doc(**metrics))


def response(**metrics) -> dict:
    return committee_from_agents(agents_doc(**metrics)).model_dump(mode="json")


def state(**metrics) -> str:
    return committee(**metrics)["conclusion"]["state"]


def evaluation(doc: dict, strategy: str) -> dict:
    return next(e for e in doc["evaluations"] if e["strategyId"] == strategy)


def clone(doc: dict) -> dict:
    return copy.deepcopy(doc)
