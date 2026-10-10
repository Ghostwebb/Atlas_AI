"""Pure committee rules over ONE published agents response (agents.v1.1 JSON).

Nothing here changes an agent evaluation, averages scores, picks a winner or produces an order.
Every finding cites published evidence by id and by the path agents.snapshot.metrics.<id>.
"""

from app.committee import config as C

AGENT_PREFIX = "agents."
METRIC_PREFIX = "snapshot.metrics."
DIRECTIONS = ("favorable", "unfavorable", "neutral")


# --- reading the agents document ---------------------------------------------------------------

def _evaluations(agents: dict) -> dict[str, dict]:
    return {e["strategyId"]: e for e in agents["evaluations"]}


def _metric_id(path: str) -> str:
    return path.removeprefix(METRIC_PREFIX)


def _evidence(e: dict):
    for direction in DIRECTIONS:
        for item in e["evidence"][direction]:
            yield direction, item


def _ref(source: str, item: dict, strategy: str, ref: dict, direction: str | None = None) -> dict:
    return {"source": source, "id": item["id"], "strategyId": strategy,
            "criterion": item.get("criterion"), "direction": direction,
            "path": AGENT_PREFIX + ref["path"], "value": ref["value"], "unit": ref["unit"]}


def _evidence_refs(strategy: str, direction: str, item: dict) -> list[dict]:
    return [_ref("evidence", item, strategy, r, direction) for r in item["references"]]


def _finding(fid: str, kind: str, statement: str, references: list[dict], level: str | None = None) -> dict:
    out = {"id": fid, "kind": kind, "statement": statement, "references": references}
    if level is not None:
        out["level"] = level
    return out


def _core_items(e: dict, direction: str) -> list[dict]:
    return [item for item in e["evidence"][direction] if item["core"]]


def _criterion(e: dict, criterion: str) -> tuple[str | None, dict | None]:
    """Direction of a criterion ('not_evaluated' when it was not evaluated), and its item."""
    for direction, item in _evidence(e):
        if item["criterion"] == criterion:
            return direction, item
    for item in e["notEvaluated"]:
        if item["criterion"] == criterion:
            return "not_evaluated", item
    return None, None


# --- independence of evidence -------------------------------------------------------------------

def independent_bases(evaluations: dict[str, dict], strategies: list[str], direction: str) -> list[list[str]]:
    """Groups of strategies whose core evidence in `direction` shares no metric (connected components).

    Two perspectives resting on the same metric are ONE base, not two confirmations."""
    metrics = {s: {_metric_id(r["path"]) for item in _core_items(evaluations[s], direction)
                   for r in item["references"]} for s in strategies}
    parent = {s: s for s in strategies}

    def find(s):
        while parent[s] != s:
            s = parent[s]
        return s

    for i, a in enumerate(strategies):
        for b in strategies[i + 1:]:
            if metrics[a] & metrics[b]:
                parent[find(b)] = find(a)
    groups: dict[str, list[str]] = {}
    for s in strategies:
        groups.setdefault(find(s), []).append(s)
    return sorted(groups.values())


def shared_evidence(agents: dict) -> list[dict]:
    """Metrics cited by the evidence of two or more strategies (one fact, several citations)."""
    citations: dict[str, list[dict]] = {}
    for strategy, e in _evaluations(agents).items():
        for direction, item in _evidence(e):
            for r in item["references"]:
                citations.setdefault(r["path"], []).append(
                    {"evidenceId": item["id"], "strategyId": strategy, "direction": direction})
    shared = []
    for path, cited in sorted(citations.items()):
        if len({c["strategyId"] for c in cited}) >= 2:
            shared.append({"path": AGENT_PREFIX + path, "citedBy": cited,
                           "statement": f"{_metric_id(path)} is one fact cited by "
                                        f"{len({c['strategyId'] for c in cited})} perspectives; "
                                        "it is not independent confirmation."})
    return shared


# --- committee --------------------------------------------------------------------------------

def build_committee(agents: dict) -> dict:
    ev = _evaluations(agents)
    names = {s: ev[s]["name"] for s in ev}

    participants, abstentions = [], []
    for strategy in (*C.OPPORTUNITY, C.RISK):
        e = ev[strategy]
        participates = e["status"] != "insufficient"
        entry = {"strategyId": strategy, "role": "risk" if strategy == C.RISK else "opportunity",
                 "status": e["status"], "stance": e["stance"], "coverage": e["coverage"],
                 "participates": participates}
        participants.append(entry)
        if not participates:
            causes = sorted({i["reason"] for i in e["notEvaluated"] if i["core"]})
            abstentions.append({"id": f"abstention:{strategy}", "strategyId": strategy, "reason": "insufficient",
                                "causes": causes,
                                "statement": f"{names[strategy]} abstains: core criteria not evaluable "
                                             f"({', '.join(causes)}). An abstention is not neutral and not favorable.",
                                "references": [_ref("not_evaluated", i, strategy, r) for i in e["notEvaluated"]
                                               if i["core"] for r in i["references"]]})

    opp = [s for s in C.OPPORTUNITY if ev[s]["status"] != "insufficient"]
    fav = [s for s in opp if ev[s]["stance"] == "favorable"]
    unf = [s for s in opp if ev[s]["stance"] == "unfavorable"]
    aegis = ev[C.RISK]
    aegis_in = aegis["status"] != "insufficient"

    # Arguments / counterpoints come from participating OPPORTUNITY perspectives only.
    arguments, counterpoints = [], []
    for s in opp:
        for item in ev[s]["evidence"]["favorable"]:
            arguments.append(_finding(f"argument:{item['id']}", "argument", f"{names[s]}: {item['statement']}",
                                      _evidence_refs(s, "favorable", item)))
        for item in ev[s]["evidence"]["unfavorable"]:
            counterpoints.append(_finding(f"counterpoint:{item['id']}", "counterpoint",
                                          f"{names[s]}: {item['statement']}", _evidence_refs(s, "unfavorable", item)))

    # Risk: AEGIS is a gate. Its unfavorable criteria are observed risk; the rest is a risk profile.
    observed_risks, risk_profile, unevaluated = [], [], []
    if aegis_in:
        for direction, item in _evidence(aegis):
            target = observed_risks if direction == "unfavorable" else risk_profile
            label = "observed risk exposure" if direction == "unfavorable" else \
                "lower or moderate observed exposure (not safety)"
            target.append(_finding(f"aegis:{item['id']}", "risk_exposure" if direction == "unfavorable"
                                   else "risk_profile", f"AEGIS {label}: {item['statement']}",
                                   _evidence_refs(C.RISK, direction, item)))
    for s, e in ev.items():
        for risk in e["risks"]:
            observed_risks.append(_finding(f"risk:{risk['id']}", "observed_risk", f"{names[s]}: {risk['statement']}",
                                           [_ref("risk", risk, s, r) for r in risk["references"]]))
        for risk in e["risksNotEvaluated"]:
            unevaluated.append(_finding(f"unevaluated:{risk['id']}", "risk_not_evaluated",
                                        f"{names[s]}: {risk['statement']} Not evaluated is not the same as no risk.",
                                        [_ref("risk_not_evaluated", risk, s, r) for r in risk["references"]]))

    # Conflicts: stance-level between opportunity perspectives, criterion-level tensions, risk tensions.
    conflicts = []
    for i, a in enumerate(opp):
        for b in opp[i + 1:]:
            pair = {ev[a]["stance"], ev[b]["stance"]}
            if pair == {"favorable", "unfavorable"}:
                kind = C.PAIR_KINDS[frozenset({a, b})]
                f, u = (a, b) if ev[a]["stance"] == "favorable" else (b, a)
                refs = [r for item in _core_items(ev[f], "favorable") for r in _evidence_refs(f, "favorable", item)] + \
                       [r for item in _core_items(ev[u], "unfavorable") for r in _evidence_refs(u, "unfavorable", item)]
                conflicts.append(_finding(f"conflict:{kind}", kind,
                                          f"{names[f]} is favorable while {names[u]} is unfavorable on the same snapshot.",
                                          refs, level="stance"))
    nova_fav = "nova" in fav
    argo_val, argo_val_item = _criterion(ev["argo"], C.ARGO_VALUATION_CRITERION)
    if nova_fav and argo_val == "unfavorable" and "argo" not in unf:
        conflicts.append(_finding(
            "tension:valuation_vs_growth", "valuation_vs_growth",
            "NOVA reads growth as favorable while ARGO's P/E criterion is unfavorable: growth may already be priced in "
            "(ARGO is a limited P/E lens, not an intrinsic valuation).",
            [r for item in _core_items(ev["nova"], "favorable") for r in _evidence_refs("nova", "favorable", item)]
            + _evidence_refs("argo", "unfavorable", argo_val_item), level="criterion"))
    aegis_core_unf = [i for i in aegis["evidence"]["unfavorable"] if i["criterion"] in C.AEGIS_CORE_RISK_CRITERIA] \
        if aegis_in else []
    vector_vol_risk = [r for r in ev["vector"]["risks"] if r["id"] == "vector.high_recent_volatility"]
    if "vector" in fav and (aegis_core_unf or vector_vol_risk or (aegis_in and aegis["stance"] == "unfavorable")):
        refs = [r for item in _core_items(ev["vector"], "favorable") for r in _evidence_refs("vector", "favorable", item)]
        refs += [r for item in aegis_core_unf for r in _evidence_refs(C.RISK, "unfavorable", item)]
        refs += [_ref("risk", risk, "vector", r) for risk in vector_vol_risk for r in risk["references"]]
        conflicts.append(_finding("tension:momentum_with_high_risk", "momentum_with_high_risk",
                                  "VECTOR reads momentum as favorable while observed volatility or drawdown is high: "
                                  "momentum can reverse and past movement is not a prediction.", refs, level="risk"))

    # Observations that limit any reading.
    observations = []
    for s in opp:
        e = ev[s]
        if e["status"] == "partial":
            observations.append(_finding(
                f"partial:{s}", "partial_evaluation",
                f"{names[s]} is partial: coverage {e['coverage']:.2f}; not evaluated: "
                + ", ".join(f"{i['criterion']} ({i['reason']})" for i in e["notEvaluated"]) + ".",
                [_ref("not_evaluated", i, s, r) for i in e["notEvaluated"] for r in i["references"]]))
    if opp and not fav and not unf:
        observations.append(_finding("insufficient_direction", "insufficient_directional_evidence",
                                     "No participating opportunity perspective has a directional stance.", []))
    invalid_blocking = [(s, i) for s, e in ev.items() for i in e["notEvaluated"]
                        if i["core"] and i["reason"] == "invalid_input"]
    for s, item in invalid_blocking:
        observations.append(_finding(f"invalid:{item['id']}", "invalid_input_blocking",
                                     f"{names[s]}: core criterion {item['criterion']} not evaluable because of invalid "
                                     "input observations; strong conclusions are blocked.",
                                     [_ref("not_evaluated", item, s, r) for r in item["references"]]))

    # Agreements (with independence).
    agreements = []
    for direction, group in (("favorable", fav), ("unfavorable", unf)):
        if len(group) >= 2:
            bases = independent_bases(ev, group, direction)
            agreements.append({
                "id": f"agreement:{direction}", "direction": direction, "strategies": group,
                "independentBases": len(bases), "bases": bases,
                "statement": f"{len(group)} perspectives are {direction}, resting on {len(bases)} independent "
                             "evidence base(s). Agreement is not a probability of success."})

    # Requirements for aligned_favorable (all must hold).
    fav_bases = len(independent_bases(ev, fav, "favorable")) if fav else 0
    req = [
        ("R1", len(opp) >= C.MIN_PARTICIPANTS, f"At least {C.MIN_PARTICIPANTS} opportunity perspectives are evaluable"),
        ("R2", len(fav) >= C.MIN_ALIGNED, f"At least {C.MIN_ALIGNED} opportunity perspectives are favorable"),
        ("R3", not unf, "No opportunity perspective is unfavorable"),
        ("R4", bool(fav) and all(ev[s]["coverage"] >= C.MIN_COVERAGE_FOR_ALIGNMENT for s in fav),
         f"Each favorable perspective has coverage >= {C.MIN_COVERAGE_FOR_ALIGNMENT}"),
        ("R5", fav_bases >= C.MIN_INDEPENDENT_BASES,
         f"At least {C.MIN_INDEPENDENT_BASES} independent evidence bases (shared metrics count once)"),
        ("R6", aegis["status"] == "complete" and aegis["stance"] != "unfavorable" and not aegis_core_unf,
         "AEGIS risk gate evaluated completely, with no unfavorable stance and no unfavorable volatility/drawdown"),
        ("R7", not any(e["risks"] for e in ev.values()), "No observed risk flags in any evaluation"),
        ("R8", not any(e["risksNotEvaluated"] for e in ev.values()), "Every risk check could be evaluated"),
        ("R9", argo_val in ("favorable", "neutral"),
         "ARGO's P/E criterion was evaluated and is not unfavorable (valuation is only a limited P/E lens)"),
    ]
    requirements = [{"id": rid, "met": met, "statement": text} for rid, met, text in req]
    met = {r["id"]: r["met"] for r in requirements}
    unf_ok = [s for s in unf if ev[s]["coverage"] >= C.MIN_COVERAGE_FOR_ALIGNMENT]
    unf_bases = len(independent_bases(ev, unf_ok, "unfavorable")) if unf_ok else 0

    if len(opp) < C.MIN_PARTICIPANTS:
        state, rules = "insufficient_data", ["fewer_than_min_participants"]
    elif fav and unf:
        state, rules = "conflicted", ["opposite_stances"]
    elif len(unf_ok) >= C.MIN_ALIGNED and unf_bases >= C.MIN_INDEPENDENT_BASES:
        state, rules = "aligned_unfavorable", ["unfavorable_convergence"]
    elif all(met.values()):
        state, rules = "aligned_favorable", ["all_requirements_met"]
    elif fav:
        state, rules = "caution", ["unmet:" + r["id"] for r in requirements if not r["met"]]
    else:
        state, rules = "neutral", ["no_sufficient_direction"]

    conditions = [{"id": f"condition:{r['id']}", "statement": f"Not satisfied: {r['statement']}."}
                  for r in requirements if not r["met"]] if state in ("caution", "neutral", "conflicted") else []
    missing = sorted({(m, s) for s, e in ev.items() for m in e["missingData"]})
    missing_data = [{"metric": m, "path": f"{AGENT_PREFIX}{METRIC_PREFIX}{m}", "strategyId": s,
                     "status": agents["snapshot"]["metrics"][m]["status"]} for m, s in missing]

    summary = {
        "insufficient_data": f"Only {len(opp)} opportunity perspective(s) are evaluable; no committee reading is "
                             "possible.",
        "conflicted": f"Material opposite readings: favorable ({', '.join(names[s] for s in fav)}) versus unfavorable "
                      f"({', '.join(names[s] for s in unf)}).",
        "aligned_unfavorable": f"{len(unf_ok)} perspectives converge unfavorably on {unf_bases} independent evidence "
                               "bases.",
        "aligned_favorable": f"{len(fav)} perspectives converge favorably on {fav_bases} independent evidence bases "
                             "and every risk requirement is met. Convergence is not a probability of success.",
        "caution": f"Favorable reading from {', '.join(names[s] for s in fav)}, with unmet requirements: "
                   + ", ".join(r["id"] for r in requirements if not r["met"]) + ".",
        "neutral": "No sufficient directional signal. Neutral does not mean low risk.",
    }[state]

    return {
        "conclusion": {"state": state, "policyVersion": C.POLICY_VERSION, "rulesApplied": rules,
                       "summary": summary, "requirements": requirements,
                       "notice": "Not an order, not a recommendation for a person and not a probability. "
                                 "No user objective, horizon, risk tolerance or portfolio is known."},
        "participants": participants, "abstentions": abstentions, "agreements": agreements,
        "conflicts": conflicts, "observations": observations, "arguments": arguments,
        "counterpoints": counterpoints, "observedRisks": observed_risks, "riskProfile": risk_profile,
        "unevaluatedRisks": unevaluated, "missingData": missing_data, "sharedEvidence": shared_evidence(agents),
        "conditions": conditions,
        "limitations": [
            "ARGO is a limited P/E lens (P/E, margin, value-trap check), not a full or intrinsic valuation.",
            "AEGIS describes observed past risk exposure; it never means safe.",
            "Perspectives share metrics; shared facts are listed once in sharedEvidence and are not independent votes.",
            "Synthetic demo data; no user objective, portfolio, intrinsic value or prediction.",
        ],
    }
