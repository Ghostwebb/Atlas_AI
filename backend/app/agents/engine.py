"""Pure evaluation of a strategy over a shared snapshot, plus reference validation."""

from app.agents.config import STANCE_BAND
from app.agents.snapshot import _SEVERITY, AgentSnapshot
from app.agents.strategies import POINTS, Assessment, Strategy

METRICS_PATH = "snapshot.metrics."


class EvidenceIntegrityError(Exception):
    """An evidence reference does not resolve to the published snapshot."""


def _ref(snapshot: AgentSnapshot, metric_id: str) -> dict:
    metric = snapshot.metrics[metric_id]
    return {"path": METRICS_PATH + metric_id, "value": metric.value, "unit": metric.unit}


def _unavailable(snapshot: AgentSnapshot, metric_ids) -> list[str]:
    return [m for m in metric_ids if snapshot.metrics[m].value is None]


def _cause(snapshot: AgentSnapshot, absent: list[str]) -> str:
    """Most severe publication status among the unavailable inputs (invalid > not computable >
    insufficient history > missing)."""
    return max((snapshot.metrics[m].status for m in absent), key=lambda status: _SEVERITY[status])


def _describe(snapshot: AgentSnapshot, absent: list[str]) -> str:
    return "; ".join(f"{m} {snapshot.metrics[m].status}" + (f" ({snapshot.metrics[m].issue})"
                                                            if snapshot.metrics[m].issue else "") for m in absent)


def evaluate(strategy: Strategy, snapshot: AgentSnapshot) -> dict:
    values = {key: metric.value for key, metric in snapshot.metrics.items()}
    evidence = {"favorable": [], "unfavorable": [], "neutral": []}
    not_evaluated = []
    missing: set[str] = set()
    weighted_points = 0.0
    evaluated_weight = 0.0
    core_directions: list[str | None] = []

    for criterion in strategy.criteria:
        absent = _unavailable(snapshot, criterion.metrics)
        if absent:
            # Absence propagates: an unavailable input never yields a direction or a 0.
            missing.update(absent)
            assessment = Assessment(None, _cause(snapshot, absent), "Not evaluated: " + _describe(snapshot, absent) + ".")
        else:
            assessment = criterion.assess(values)
        refs = [_ref(snapshot, m) for m in criterion.metrics]
        base = {"id": f"{strategy.id}.{criterion.id}", "criterion": criterion.id, "label": criterion.label,
                "weight": criterion.weight, "core": criterion.core, "statement": assessment.statement,
                "references": refs}
        if criterion.core:
            core_directions.append(assessment.direction)
        if assessment.direction is None:
            not_evaluated.append({**base, "reason": assessment.reason})
            continue
        evidence[assessment.direction].append({**base, "direction": assessment.direction, "rule": criterion.rule})
        weighted_points += POINTS[assessment.direction] * criterion.weight
        evaluated_weight += criterion.weight

    total_weight = sum(c.weight for c in strategy.criteria)
    coverage = round(evaluated_weight / total_weight, 4)
    if None in core_directions:
        status, score, stance = "insufficient", None, "insufficient_data"
    else:
        status = "partial" if not_evaluated else "complete"
        score = round(weighted_points / evaluated_weight, 4)
        if score >= STANCE_BAND and "favorable" in core_directions and "unfavorable" not in core_directions:
            stance = "favorable"
        elif score <= -STANCE_BAND and "unfavorable" in core_directions and "favorable" not in core_directions:
            stance = "unfavorable"
        else:
            stance = "neutral"

    risks, risks_not_evaluated = [], []
    for rule in strategy.risks:
        absent = _unavailable(snapshot, rule.metrics)
        if absent:
            # "Could not check" is reported as such: never as "no risk" and never as "high risk".
            risks_not_evaluated.append({"id": rule.id, "reason": _cause(snapshot, absent),
                                        "statement": "Risk check not evaluated: " + _describe(snapshot, absent) + ".",
                                        "references": [_ref(snapshot, m) for m in rule.metrics]})
            continue
        statement = rule.check(values)
        if statement is not None:
            risks.append({"id": rule.id, "statement": statement,
                          "references": [_ref(snapshot, m) for m in rule.metrics]})

    return {
        "strategyId": strategy.id, "name": strategy.name, "style": strategy.style, "version": strategy.version,
        "lens": strategy.lens, "stanceMeaning": strategy.stance_meaning,
        "status": status, "stance": stance, "score": score, "coverage": coverage,
        "evidence": evidence, "notEvaluated": not_evaluated, "risks": risks,
        "risksNotEvaluated": risks_not_evaluated,
        "missingData": sorted(missing), "limitations": list(strategy.limitations),
    }


def _resolve(document: dict, path: str):
    node = document
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise EvidenceIntegrityError(f"reference {path} does not resolve")
        node = node[part]
    return node


def validate_references(document: dict) -> None:
    """Every reference must resolve to a published metric with the same value and unit.

    Evidence and risks must cite present (non-null) values; not-evaluated items may cite nulls.
    """
    problems: list[str] = []
    for evaluation in document["evaluations"]:
        groups = [(item, True) for direction in ("favorable", "unfavorable", "neutral")
                  for item in evaluation["evidence"][direction]]
        groups += [(item, True) for item in evaluation["risks"]]
        groups += [(item, False) for item in evaluation["notEvaluated"]]
        groups += [(item, False) for item in evaluation["risksNotEvaluated"]]
        for item, must_have_value in groups:
            for ref in item["references"]:
                if not ref["path"].startswith(METRICS_PATH):
                    problems.append(f"{item['id']}: reference outside the snapshot ({ref['path']})")
                    continue
                try:
                    metric = _resolve(document, ref["path"])
                except EvidenceIntegrityError as error:
                    problems.append(f"{item['id']}: {error}")
                    continue
                if metric["value"] != ref["value"] or metric["unit"] != ref["unit"]:
                    problems.append(f"{item['id']}: reference {ref['path']} does not match the snapshot")
                if must_have_value and ref["value"] is None:
                    problems.append(f"{item['id']}: evidence cites a missing metric {ref['path']}")
    if problems:
        raise EvidenceIntegrityError("; ".join(problems))
