# Phase 8: supervised investment committee (backend)

A deterministic committee compares the four Phase 7 strategy evaluations of one symbol on one
snapshot. It explains agreements, conflicts, risks and limits.

- **What it never does:** it does **not** choose an investment, pick a winning agent, average scores, predict returns, create paper proposals or place, confirm or authorize orders. No agent and no committee may execute operations automatically.
- **Rules, not an LLM:** the committee is explicit rules in `backend/app/committee/`, with no Gemma call. A later narration may explain the result but never replace its facts.
- **Base:** `feat/phase-7-investment-agents` at `fd24f75` (PR #7, still open). This PR targets that branch. Once PR #7 is merged, retarget this PR to `main`; no code change is needed.
- **Inputs:** agents contract `agents.v1.1`, strategies `1.0.1`. Committee: `committee.v1`, policy `1.0.0`.

## 1. Meaning of the conclusion

The conclusion states how much the perspectives converge on the published evidence for this
symbol. It is **not** a recommendation for a person: no user objective, horizon, risk tolerance or
portfolio is known, so the reading stays general and limited to the evidence. "Aligned" is not a
probability of success, and "neutral" does not mean low risk.

## 2. Roles

| Role | Strategies | How it participates |
|---|---|---|
| Opportunity | ARGO (a limited P/E lens: P/E, margin, value-trap check), NOVA (growth), VECTOR (momentum) | Their favorable evidence becomes **arguments**; their unfavorable evidence becomes **counterpoints** |
| Risk | AEGIS | A **risk gate**, never an extra vote on returns. Unfavorable criteria → **observedRisks**; favorable or neutral → **riskProfile** ("lower observed exposure, not safety") |

- **Abstention:** an `insufficient` evaluation abstains (`participates: false`). It is listed in `abstentions` with the causes of its core criteria (for example `invalid_input`). It is **not** neutral and **not** favorable, and its evidence is not used as arguments.
- **Partial evaluations** participate. Their coverage and their not-evaluated criteria stay visible (`observations: partial_evaluation`).
- **Scores are never added or averaged:** the perspectives measure different things.

## 3. States and precedence (the first rule that holds wins)

| # | State | Rule |
|---|---|---|
| 1 | `insufficient_data` | Fewer than **2** opportunity perspectives are evaluable |
| 2 | `conflicted` | Opportunity perspectives are both favorable and unfavorable |
| 3 | `aligned_unfavorable` | ≥ 2 opportunity perspectives unfavorable with coverage ≥ 0.75, none favorable, and ≥ 2 independent evidence bases |
| 4 | `aligned_favorable` | **All** requirements R1–R9 hold |
| 5 | `caution` | At least one favorable and none unfavorable, but some of R1–R9 are not met (listed as `conditions`) |
| 6 | `neutral` | No sufficient directional signal, including a single unfavorable perspective. Not low risk |

Requirements for `aligned_favorable` (`conclusion.requirements[]` reports each one as met or not):

| Id | Requirement |
|---|---|
| R1 | ≥ 2 opportunity perspectives evaluable (a single available agent never produces a consensus) |
| R2 | ≥ 2 opportunity perspectives favorable |
| R3 | No opportunity perspective unfavorable |
| R4 | Each favorable perspective has coverage ≥ **0.75** (`coverage` measures scored criteria only) |
| R5 | ≥ **2 independent evidence bases**; shared metrics count once (section 5) |
| R6 | AEGIS is `complete`, its stance is not unfavorable, and its volatility and max-drawdown criteria are not unfavorable |
| R7 | No observed risk flags (`risks[]`) in any evaluation: a high risk does not disappear because others are favorable |
| R8 | Every risk check could run (`risksNotEvaluated[]` empty): not evaluated ≠ no risk |
| R9 | ARGO's P/E criterion was evaluated and is not unfavorable. Missing or unattractive valuation limits any claim of fundamental attractiveness, and ARGO is never called a full valuation |

Invalid or insufficient data in essential criteria blocks strong conclusions:

- the agent abstains, and the committee lists an `invalid_input_blocking` observation;
- when the abstaining agent is AEGIS, R6 fails;
- when ARGO's P/E cannot be evaluated, R9 fails.

All values are in `backend/app/committee/config.py`.

## 4. Findings (deterministic templates over published facts)

- **Conflicts**, each with a `level`:
  - `stance`: opposite stances. The kind is `growth_vs_momentum`, `valuation_vs_growth` or `valuation_vs_momentum`.
  - `criterion`: NOVA favorable while ARGO's P/E criterion is unfavorable (`valuation_vs_growth`).
  - `risk`: VECTOR favorable with high observed volatility or drawdown (`momentum_with_high_risk`).
- **Observations:** `partial_evaluation`, `insufficient_directional_evidence` and `invalid_input_blocking`.
- **Separate lists:**
  - `arguments`, `counterpoints`;
  - `observedRisks` (AEGIS unfavorable criteria plus every agent's `risks`), `riskProfile`, `unevaluatedRisks`;
  - `missingData`, `conditions` (unmet requirements), `limitations`.
- **Agreements:** strategies, direction, number of independent bases and the bases themselves.

## 5. Shared evidence and independence

- **`sharedEvidence` lists every metric cited by two or more perspectives**, for example `profit_margin` (ARGO, NOVA, AEGIS) and `earnings_growth` (ARGO, NOVA). It is one fact with several citations, never independent confirmation.
- **Independent bases are counted** as the connected components of the agreeing perspectives, linked when their **core** evidence in that direction cites a common metric. Two perspectives resting on the same metric are **one** base.
- **There is no global confidence or certainty percentage.**

## 6. Traceability and integrity

Every committee reference carries these fields:

- `source` (`evidence`, `risk`, `risk_not_evaluated` or `not_evaluated`);
- the cited item `id` (for example `nova.revenue_growth`), `strategyId`, `criterion` and `direction`;
- `path` (`agents.snapshot.metrics.<id>`), `value` and `unit`.

Before responding, the server validates:

- the Phase 7 references inside `agents` (relative to `agents`);
- that every committee reference resolves inside this response and the cited item exists for that strategy;
- that criterion and direction match and that the metric is cited by that item;
- that value and unit match;
- that no evidence or risk cites a null metric, and that there are no paths outside the published snapshot;
- that participants match the evaluations (no evaluation is modified).

Any failure → **HTTP 500** `Committee integrity error`, never a silent neutral conclusion. An
unsupported agents schema is also rejected.

## 7. HTTP contract

`POST /api/committee/analyze` with body `{"symbol": "NVDA"}`.

- Normalization and errors are those of `/api/analyze` (400 invalid, 404 unknown).
- Extra fields are rejected (400): evaluations, votes, weights, metrics, URLs, recommendations, policy.
- **One** agents evaluation per request (one provider query, tested). Deterministic output, no timestamps.

```text
schemaVersion: "committee.v1", policyVersion: "1.0.0", notice
agents:    <the agents.v1.1 response, unchanged; equal to POST /api/agents/analyze>
committee: { conclusion{state, policyVersion, rulesApplied[], summary, requirements[{id, met, statement}], notice},
             participants[{strategyId, role, status, stance, coverage, participates}],
             abstentions[{id, strategyId, reason, causes[], statement, references[]}],
             agreements[{id, direction, strategies[], independentBases, bases[[...]], statement}],
             conflicts[], observations[], arguments[], counterpoints[], observedRisks[], riskProfile[],
             unevaluatedRisks[]   // findings: {id, kind, statement, level?, references[]}
             missingData[{metric, path, strategyId, status}], sharedEvidence[{path, citedBy[], statement}],
             conditions[{id, statement}], limitations[] }
```

`/api/analyze`, `/api/report` and `/api/agents/analyze` are unchanged (tested). The engine's
BUY/HOLD/SELL recommendation is not modified and is not used by the committee.

## 8. Real results (generated by this code; **synthetic data**)

| Symbol | Stances ARGO/NOVA/VECTOR/AEGIS | Committee | Unmet | Conflicts / tensions | Observed risks |
|---|---|---|---|---|---|
| AAPL | neutral/neutral/unfavorable/neutral | neutral | R2,R3,R4,R5,R9 | — | aegis:aegis.current_drawdown |
| MSFT | neutral/neutral/neutral/favorable | neutral | R2,R4,R5,R9 | — | — |
| NVDA | neutral/favorable/favorable/neutral | **caution** | R6,R7,R9 | valuation_vs_growth (criterion), momentum_with_high_risk (risk) | aegis:aegis.volatility, risk:vector.high_recent_volatility |
| TSLA | unfavorable ×4 | aligned_unfavorable | R2–R7,R9 | — | aegis volatility, max/current drawdown, nova.growth_not_reaching_earnings, vector.high_recent_volatility |
| AMZN | unfavorable/neutral/unfavorable/neutral | aligned_unfavorable | R2,R3,R4,R5,R9 | — | aegis:aegis.current_drawdown |
| GOOGL | neutral/neutral/neutral/favorable | neutral | R2,R4,R5 | — | — |
| META | neutral/favorable/unfavorable/neutral | **conflicted** | R2,R3,R5,R7,R9 | growth_vs_momentum (stance), valuation_vs_growth (criterion) | aegis:aegis.current_drawdown, risk:vector.high_recent_volatility |

The requirements are those of `aligned_favorable`, so they are reported as unmet for every other
state too. None of the demo symbols reaches `aligned_favorable`. That is a consequence of the
rules, which were not tuned.

**NVDA (excerpt).** NOVA and VECTOR agree on 2 independent bases, but the risk gate and the
valuation lens block the alignment:

```json
{"conclusion": {"state": "caution", "policyVersion": "1.0.0", "rulesApplied": ["unmet:R6", "unmet:R7", "unmet:R9"],
  "summary": "Favorable reading from NOVA, VECTOR, with unmet requirements: R6, R7, R9."},
 "agreements": [{"id": "agreement:favorable", "direction": "favorable", "strategies": ["nova", "vector"],
   "independentBases": 2, "bases": [["nova"], ["vector"]]}],
 "conflicts": [..., {"id": "tension:momentum_with_high_risk", "level": "risk", "references": [
   {"source": "evidence", "id": "vector.return_60d", "strategyId": "vector", "criterion": "return_60d",
    "direction": "favorable", "path": "agents.snapshot.metrics.return_60d", "value": 0.566591, "unit": "decimal"},
   {"source": "evidence", "id": "aegis.volatility", "strategyId": "aegis", "criterion": "volatility",
    "direction": "unfavorable", "path": "agents.snapshot.metrics.volatility_annualized", "value": 0.486943, "unit": "decimal"},
   {"source": "risk", "id": "vector.high_recent_volatility", "strategyId": "vector",
    "path": "agents.snapshot.metrics.volatility_20d", "value": 0.525752, "unit": "decimal"}]}],
 "sharedEvidence": [{"path": "agents.snapshot.metrics.earnings_growth", "citedBy": [
   {"evidenceId": "argo.value_trap", "strategyId": "argo", "direction": "neutral"},
   {"evidenceId": "nova.earnings_growth", "strategyId": "nova", "direction": "favorable"}]}, ...],
 "conditions": [{"id": "condition:R6", "statement": "Not satisfied: AEGIS risk gate evaluated completely, ..."}, ...]}
```

## 9. Tests (58 new; full backend suite 614)

- **`tests/test_committee_rules.py`** uses controlled, validated evaluations produced by the real Phase 7 engine (`tests/committee_factories.py`). It covers:
  - every state and the precedence between them;
  - each requirement failing on its own, and the exact coverage boundary (0.75 / 0.7499);
  - all agents insufficient, a single available agent, insufficient never counted, partial evaluations;
  - high risk with favorable opportunity, unevaluated risks, the AEGIS role;
  - growth vs momentum, valuation vs growth (stance and criterion), aligned unfavorable, neutral, single unfavorable;
  - shared evidence, and two perspectives on one core metric counted as one base;
  - invalid inputs, untouched evaluations, determinism, no confidence or winner.
- **`tests/test_committee_api.py`** covers:
  - the 7 demo symbols (pinned states), `agents` equal to `/api/agents/analyze`, data-driven findings;
  - normalization, HTTP errors and extra fields;
  - one provider query and determinism;
  - integrity failure → 500, and ten kinds of tampering rejected (path, outside path, value, unit, direction, strategy, id, wrong metric, participant, agents evidence);
  - null metric as evidence, abstention references, NaN/inf inputs without NaN in JSON;
  - no orders, proposals or paper routes, no Gemma or network calls;
  - previous contracts unchanged.

Mutation checks (each fails tests):

| Mutation | Failing tests |
|---|---|
| Insufficient agent counted as favorable | 5 |
| Observed risk flags ignored (R7) | 2 |
| AEGIS volatility/drawdown ignored (R6) | 3 |
| `aligned_favorable` with only R2+R3 | 12 |
| Broken evidence paths | 27 |
| Shared core evidence counted as independent | 1 |

## 10. Frontend handoff (later PR; `codex/agents-workspace` is not modified here)

The committee view currently renders authored fixtures (`committeeFixtures`, `Decision.selectedAgentId`).
To connect it:

- **Call `POST /api/committee/analyze`.** Show `notice` and the synthetic provenance (`agents.snapshot.provenance`) permanently.
- **Map** `committee.participants[].strategyId` to the profiles `argo`, `nova`, `vector` and `aegis`. Show each agent's `stance`, `status` and `coverage` from `agents.evaluations` (never "Comprar" or "Esperar" as an action).
- **Replace the fixture `Decision`** with `committee.conclusion` (`state`, `summary`, `requirements`, `conditions`). There is **no `selectedAgentId`**: the committee never picks a winning agent, so do not infer one from scores.
- **Show** `conflicts` (with `level`), `agreements` (with `independentBases`), `arguments`/`counterpoints`, `observedRisks`/`riskProfile`/`unevaluatedRisks`, `abstentions`, `missingData`, `sharedEvidence` and `limitations`.
- **Resolve every `references[].path`** against the same response to show values with units.
- **No investment buttons:** do not connect the conclusion to Paper Trading or to any order.

## 11. Limitations

- **No user context:** no objective, horizon, risk tolerance or portfolio, so there is no allocation, diversification or suitability.
- **No valuation model:** no intrinsic valuation. ARGO is a limited P/E lens.
- **No prediction:** past movement and risk are observations, not forecasts.
- **Synthetic, undated data:** synthetic prices and undated fundamentals; every result is illustrative.
- **Heuristic rules:** the policy thresholds (2 participants, coverage 0.75, 2 independent bases) are documented heuristics, not calibrated against outcomes.
