"""Integrity checks: the committee only cites published evidence, and never alters an evaluation."""

from app.agents.engine import EvidenceIntegrityError, validate_references
from app.committee.rules import AGENT_PREFIX

METRICS_PATH = AGENT_PREFIX + "snapshot.metrics."
COLLECTIONS = {"evidence": None, "risk": "risks", "risk_not_evaluated": "risksNotEvaluated",
               "not_evaluated": "notEvaluated"}


class CommitteeIntegrityError(Exception):
    """A committee reference or participant does not match the published agents response."""


def _resolve(document: dict, path: str):
    node = document
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise CommitteeIntegrityError(f"reference {path} does not resolve")
        node = node[part]
    return node


def _find_item(evaluation: dict, source: str, item_id: str) -> tuple[dict | None, str | None]:
    if source == "evidence":
        for direction in ("favorable", "unfavorable", "neutral"):
            for item in evaluation["evidence"][direction]:
                if item["id"] == item_id:
                    return item, direction
        return None, None
    for item in evaluation[COLLECTIONS[source]]:
        if item["id"] == item_id:
            return item, None
    return None, None


def _committee_refs(committee: dict):
    for key in ("abstentions", "conflicts", "observations", "arguments", "counterpoints", "observedRisks",
                "riskProfile", "unevaluatedRisks"):
        for finding in committee[key]:
            for ref in finding["references"]:
                yield finding["id"], ref


def validate_committee(document: dict) -> None:
    """Raises CommitteeIntegrityError on any mismatch. Called before every response."""
    try:
        validate_references(document["agents"])   # Phase 7 references, relative to `agents`
    except EvidenceIntegrityError as error:
        raise CommitteeIntegrityError(str(error)) from error

    agents, committee = document["agents"], document["committee"]
    evaluations = {e["strategyId"]: e for e in agents["evaluations"]}
    problems: list[str] = []

    for p in committee["participants"]:
        e = evaluations.get(p["strategyId"])
        if e is None or (p["status"], p["stance"], p["coverage"]) != (e["status"], e["stance"], e["coverage"]):
            problems.append(f"participant {p['strategyId']} does not match its evaluation")
        if p["participates"] != (e is not None and e["status"] != "insufficient"):
            problems.append(f"participant {p['strategyId']}: participation does not follow its status")

    for finding_id, ref in _committee_refs(committee):
        where = f"{finding_id} -> {ref['id']}"
        if not ref["path"].startswith(METRICS_PATH):
            problems.append(f"{where}: reference outside the published snapshot ({ref['path']})")
            continue
        evaluation = evaluations.get(ref["strategyId"])
        if evaluation is None or ref["source"] not in COLLECTIONS:
            problems.append(f"{where}: unknown strategy or source")
            continue
        item, direction = _find_item(evaluation, ref["source"], ref["id"])
        if item is None:
            problems.append(f"{where}: cited item does not exist for {ref['strategyId']}")
            continue
        if ref["source"] == "evidence" and (direction != ref["direction"] or item["criterion"] != ref["criterion"]):
            problems.append(f"{where}: direction or criterion does not match the evidence")
        if ref["path"].removeprefix(AGENT_PREFIX) not in {r["path"] for r in item["references"]}:
            problems.append(f"{where}: metric is not cited by that item")
        try:
            metric = _resolve(document, ref["path"])
        except CommitteeIntegrityError as error:
            problems.append(f"{where}: {error}")
            continue
        if metric["value"] != ref["value"] or metric["unit"] != ref["unit"]:
            problems.append(f"{where}: value or unit does not match the snapshot")
        if ref["source"] in ("evidence", "risk") and ref["value"] is None:
            problems.append(f"{where}: cites a null metric as evidence")

    for shared in committee["sharedEvidence"]:
        try:
            _resolve(document, shared["path"])
        except CommitteeIntegrityError as error:
            problems.append(str(error))
    if problems:
        raise CommitteeIntegrityError("; ".join(problems))
