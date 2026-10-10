# Phase 7: investment strategy agents (backend)

Four deterministic strategies evaluate the same symbol on one shared snapshot. Each produces a
comparable, evidence-based evaluation.

- **Agents:** ARGO (value), NOVA (growth), VECTOR (momentum) and AEGIS (capital preservation). The ids `argo`, `nova`, `vector` and `aegis` match the profiles in the agent-committee design (`codex/agents-workspace`). Their authored example decisions were **not** turned into rules.
- **Rules only:** strategies are explicit rules in `backend/app/agents/`. No LLM (Gemma does not score or decide), no Alpaca, no orders, no paper proposals.
- **No committee yet:** there is no winner and no committee decision. That is Phase 8. No agent may ever execute orders automatically.
- **Base:** `main` at `e1294f8` (Phases 3–4). It does not depend on the open PRs #3–#6.

## 1. Data actually available (synthetic demo dataset)

| Source | Field | Unit | Notes |
|---|---|---|---|
| Price bars | 120 daily OHLCV bars per symbol (2026‑04‑16 → 2026‑09‑30) | USD, shares | Seeded random walk; volume is synthetic |
| Fundamentals | `revenueGrowth`, `earningsGrowth`, `profitMargin` | decimal (0.15 = 15%) | Single period, **undated** |
| Fundamentals | `peRatio` | multiple | Undated |

**Not available:** book value (P/B), cash flow, cash, debt, multi-year growth history, quotes,
portfolio, liquidity. Nothing in this phase invents them, and the dataset was **not** extended.
`/api/analyze` results are unchanged.

## 2. Shared snapshot (`snapshot.metrics`)

The provider is queried **once** per request (tested). Metrics are computed from bars up to the
last bar only (no look-ahead) and rounded to 6 decimals. The rules evaluate the rounded,
published values, so every cited number can be reproduced from the JSON. Insufficient history,
missing inputs or non-finite results give `value: null`, never 0.

| Metric | Formula | Unit | Window / minimum bars |
|---|---|---|---|
| `price_last` | last close | usd | 1 |
| `return_20d` | close[t] / close[t−20] − 1 | decimal | 21 |
| `return_60d` | close[t] / close[t−60] − 1 | decimal | 61 |
| `sma20`, `sma50` | mean of last 20 / 50 closes | usd | 20 / 50 |
| `price_vs_sma20` | price / SMA20 − 1 | decimal | 20 |
| `sma20_vs_sma50` | SMA20 / SMA50 − 1 | decimal | 50 |
| `volatility_annualized` | sample std of daily log returns × √252 | decimal | full window, ≥ 21 |
| `volatility_20d` | same, last 20 returns | decimal | 21 |
| `max_drawdown` | max(1 − close / running peak) | decimal (positive) | full window, ≥ 21 |
| `current_drawdown` | 1 − last close / window high | decimal | full window, ≥ 21 |
| `volume_ratio_20_60` | mean volume of last 20 / last 60 bars | ratio | 60 |
| `revenue_growth`, `earnings_growth`, `profit_margin` | dataset values | decimal | undated |
| `pe_ratio` | dataset value | multiple | undated |

The snapshot also publishes provenance (`synthetic` for `demo_dataset`), `isSimulated`, the
observation count, the first and last dates, `dataIssues` and `warnings`. One warning states that
fundamentals are undated and are combined with prices without a matching date.

## 3. Scoring (common to all strategies)

- **Criterion points:** each criterion gives favorable **+1**, neutral **0** or unfavorable **−1**, or is *not evaluated*:
  - `missing`: an input is null;
  - `not_interpretable`: for example P/E ≤ 0.

  A not-evaluated criterion is **never** counted as 0 or as favorable.
- **Score:** the weighted mean of points over the evaluated criteria, in [−1, 1]. It is not a probability.
- **Coverage:** evaluated weight ÷ total weight, in [0, 1]. It only measures how much of the strategy could be evaluated. It is not "confidence".
- **Status:**
  - `insufficient` if any **core** criterion is not evaluated; then score is `null` and stance is `insufficient_data`;
  - `partial` if only non-core criteria are missing;
  - otherwise `complete`.
- **Stance**, read through the strategy's lens, never an order:
  - `favorable`: score ≥ **0.25**, at least one core criterion favorable and none unfavorable;
  - `unfavorable`: score ≤ −0.25, at least one core criterion unfavorable and none favorable;
  - otherwise `neutral`.
- **Thresholds:** inclusive as written (≥, ≤); "<" bounds are strict. Values are decimals.
- **Status and thresholds are deliberately conservative heuristics.** They are not calibrated against market outcomes and were not tuned per symbol.

## 4. Strategies (all version `1.0.0`; values in `backend/app/agents/config.py`)

### ARGO: value (limited P/E lens)

| Criterion | Weight | Core | Rule |
|---|---|---|---|
| `pe_valuation` | 0.5 | ★ | P/E ≤ 15 favorable; ≥ 25 unfavorable; between neutral. **P/E ≤ 0 → not interpretable** (zero or negative earnings, never "cheap") + risk `argo.negative_earnings`. Missing P/E → `insufficient` |
| `margin_quality` | 0.3 | | margin ≥ 0.15 favorable; < 0.05 unfavorable |
| `value_trap` | 0.2 | | earnings growth < 0 unfavorable (a low multiple may reflect deterioration); otherwise neutral |

**Limitations:**
- No P/B, FCF or debt, so balance-sheet strength cannot be assessed.
- **No intrinsic value or margin of safety** is computed (no DCF, no hidden assumptions).
- P/E is an undated dataset figure.

### NOVA: growth

| Criterion | Weight | Core | Rule |
|---|---|---|---|
| `revenue_growth` | 0.4 | ★ | ≥ 0.15 favorable; < 0.05 unfavorable (negative included) |
| `earnings_growth` | 0.3 | | ≥ 0.15 favorable; < 0 unfavorable |
| `margin_sustainability` | 0.3 | | margin ≥ 0.15 favorable; < 0.05 unfavorable |

**Risks:**
- `nova.growth_not_reaching_earnings`: revenue growth > 0 and earnings growth < 0.
- `nova.unprofitable`: margin < 0.

**Rules of use:** NOVA ignores P/E (a high P/E is not evidence of growth) and never substitutes price momentum for missing growth.

**Limitation:** single-period growth, with no multi-year history or debt data.

### VECTOR: momentum

| Criterion | Weight | Core | Rule |
|---|---|---|---|
| `return_60d` | 0.35 | ★ | ≥ +0.10 favorable; ≤ −0.10 unfavorable |
| `trend_alignment` | 0.25 | ★ | price > SMA20 > SMA50 favorable; price < SMA20 < SMA50 unfavorable; otherwise neutral |
| `return_20d` | 0.25 | | ≥ +0.03 favorable; ≤ −0.03 unfavorable |
| `volume_confirmation` | 0.15 | | ratio ≥ 1.2 confirms the 20-bar direction (favorable if rising, unfavorable if falling); otherwise neutral |

**Risks** (reported separately from the evidence):
- `vector.high_recent_volatility`: `volatility_20d` ≥ 0.40;
- `vector.divergence`: the 20-bar and 60-bar returns point in opposite directions, both beyond their thresholds.

Momentum describes past movement and is **not** a prediction of returns.

### AEGIS: capital preservation (observed exposure)

| Criterion | Weight | Core | Rule |
|---|---|---|---|
| `volatility` | 0.35 | ★ | annualized ≤ 0.25 favorable; ≥ 0.45 unfavorable |
| `max_drawdown` | 0.35 | ★ | ≤ 0.15 favorable; ≥ 0.30 unfavorable |
| `current_drawdown` | 0.15 | | ≤ 0.05 favorable; ≥ 0.20 unfavorable |
| `margin_cushion` | 0.15 | | margin ≥ 0.15 favorable; < 0.05 unfavorable (the only financial-strength input available) |

**Risk:** `aegis.rising_volatility` when `volatility_20d / volatility_annualized` ≥ 1.5.

A favorable stance means **lower observed historical risk exposure**:
- it is not "safe" and does not guarantee capital preservation;
- missing data is never read as low risk;
- no hedging, derivatives or short selling is recommended.

**Not covered:** diversification and liquidity need portfolio data that does not exist.

## 5. Evaluability with the current dataset

| Agent | Status on all 7 demo symbols | What it can and cannot say |
|---|---|---|
| VECTOR | complete | Full momentum lens (bars and volume available) |
| AEGIS | complete | Volatility and drawdowns. Financial strength = margin only. No portfolio diversification or liquidity |
| NOVA | complete | Single-period growth and margin. No multi-year persistence or debt |
| ARGO | complete *for its declared criteria* | A **limited** P/E lens only. A real value assessment (P/B, FCF yield, debt, margin of safety) needs a dataset extension |

**Proposed extension** (needs authorization; not done): synthetic, documented `debtToEquity`,
`freeCashFlowMargin`, `bookValuePerShare` and two-year growth history. It would be added as new
fields with new strategy versions (`2.0.0`), without changing `/api/analyze`.

## 6. Endpoint

`POST /api/agents/analyze` with body `{"symbol": "NVDA"}`.

- The symbol is normalized (trim + uppercase), as in `/api/analyze`.
- Extra fields (metrics, weights, recommendations, URLs, strategy choices) → **400**.
- Invalid format → 400; unknown symbol → 404.
- Unverifiable references → **500** `Agent evaluation integrity error`.
- Error body: `{error, message}`.

Response (`schemaVersion: "agents.v1"`):

```text
schemaVersion, notice, limitations[]
snapshot: { symbol, companyName, dataSource, provenance, isSimulated, observations, firstDate, lastDate,
            dataIssues[], warnings[], metrics{ id: {value, unit, source, window, description} } }
evaluations[]: { strategyId, name, style, version, lens, stanceMeaning,
                 status, stance, score|null, coverage,
                 evidence{ favorable[], unfavorable[], neutral[] },   // items: id, criterion, label, direction,
                 notEvaluated[],                                       //   weight, core, rule, statement,
                 risks[], missingData[], limitations[] }               //   references[{path, value, unit}]
```

Every reference points to `snapshot.metrics.<id>` in the same response and repeats its value and
unit. Before responding, the server checks three things:

- each path resolves;
- value and unit match;
- evidence and risks never cite a null metric.

The response contains no orders, proposals, allocations, winners or BUY/SELL fields (tested), and
the output is deterministic (same input and version → identical JSON; no timestamps).

## 7. Real examples (generated by this code; **synthetic data**)

Stances (score) per symbol:

| Symbol | ARGO | NOVA | VECTOR | AEGIS |
|---|---|---|---|---|
| AAPL | neutral (-0.20) | neutral (+0.30) | unfavorable (-0.85) | neutral (+0.00) |
| MSFT | neutral (-0.20) | neutral (+0.60) | neutral (+0.00) | favorable (+0.50) |
| NVDA | neutral (-0.20) | favorable (+1.00) | favorable (+0.85) | neutral (-0.20) |
| TSLA | unfavorable (-0.70) | unfavorable (-0.70) | unfavorable (-0.85) | unfavorable (-0.85) |
| AMZN | unfavorable (-0.50) | neutral (+0.30) | unfavorable (-0.85) | neutral (-0.15) |
| GOOGL | neutral (+0.30) | neutral (+0.30) | neutral (+0.00) | favorable (+0.85) |
| META | neutral (-0.20) | favorable (+1.00) | unfavorable (-0.85) | neutral (+0.00) |

META (excerpt):

```json
{"snapshot": {"symbol": "META", "dataSource": "demo_dataset", "provenance": "synthetic", "isSimulated": true,
  "observations": 120, "firstDate": "2026-04-16", "lastDate": "2026-09-30",
  "metrics": {"return_60d": {"value": -0.198862, "unit": "decimal", "source": "price_bars", "window": "60 bars"},
              "revenue_growth": {"value": 0.15, "unit": "decimal", "source": "fundamentals", "window": null}}},
 "evaluations": [
  {"strategyId": "nova", "version": "1.0.0", "status": "complete", "stance": "favorable", "score": 1.0, "coverage": 1.0,
   "evidence": {"favorable": [{"id": "nova.revenue_growth", "direction": "favorable", "weight": 0.4, "core": true,
     "rule": ">= 0.15 favorable; < 0.05 unfavorable (decimal)", "statement": "Revenue growth 15.00%.",
     "references": [{"path": "snapshot.metrics.revenue_growth", "value": 0.15, "unit": "decimal"}]}]}},
  {"strategyId": "vector", "status": "complete", "stance": "unfavorable", "score": -0.85, "coverage": 1.0,
   "evidence": {"unfavorable": [{"id": "vector.return_60d", "statement": "60-bar return -19.89%.",
     "references": [{"path": "snapshot.metrics.return_60d", "value": -0.198862, "unit": "decimal"}]}]},
   "risks": [{"id": "vector.high_recent_volatility",
     "statement": "Recent annualized volatility 43.29%: momentum can reverse sharply.",
     "references": [{"path": "snapshot.metrics.volatility_20d", "value": 0.432898, "unit": "decimal"}]}]}]}
```

(META's revenue growth is exactly 0.15, on the inclusive favorable boundary.)

## 8. Disagreement cases (legitimate, data-driven)

- **META:** NOVA is favorable (15% revenue and 20% earnings growth, 34% margin) while VECTOR is unfavorable (−19.89% over 60 bars and an aligned downtrend). Growth fundamentals and price movement disagree.
- **NVDA:** NOVA and VECTOR are favorable. ARGO is neutral, because P/E 44 is expensive for a value lens and the 45% margin does not override valuation. AEGIS is neutral, because volatility of about 49% is unfavorable while the 24% max drawdown is neutral.
- **GOOGL:** AEGIS is favorable (low volatility and drawdown). ARGO's score is +0.30 but its stance stays **neutral**, because P/E 24 is not cheap; a strong margin alone cannot make a value case.

The thresholds were not adjusted to make agents agree or to make any symbol look attractive.

## 9. Tests (107 new; full backend suite 452)

`tests/test_agents_strategies.py`, `test_agents_snapshot.py` and `test_agents_api.py` (with
`tests/agents_factories.py`) cover:

- every rule at its exact boundaries;
- favorable, unfavorable and mixed data;
- missing and insufficient data, non-interpretable P/E (0 or negative);
- minimum history and windows, no look-ahead, non-finite values, scales and units;
- synthetic provenance and determinism;
- reference validation (broken, tampered and outside-snapshot references);
- disagreement on one snapshot;
- symbol normalization, HTTP errors and extra-field rejection;
- the 7 demo symbols;
- no model or network call, no orders or proposals;
- `/api/analyze` and `/api/report` unchanged.

Mutation checks (each fails tests):

| Mutation | Failing tests |
|---|---|
| Inverted 60-bar condition | 6 |
| Missing metric treated as favorable | 6 |
| Broken evidence path | 13 |
| `NOVA_REVENUE_FAVORABLE_MIN = 15` (percentage points instead of decimal) | 4 |

## 10. Frontend handoff (later PR; the committee view is not modified here)

- Call `POST /api/agents/analyze` with the symbol. Show `notice` and the synthetic provenance permanently.
- Map `evaluations[].strategyId` to the profile ids `argo`, `nova`, `vector` and `aegis`.
- Show `stance` with `stanceMeaning`. Never render it as Comprar/Vender or as an order.
- Show `status` and `coverage`, the evidence groups, `notEvaluated`, `risks`, `missingData` and `limitations`. Show `score` only when it is not null.
- Resolve `references[].path` against the same response to show values with their units (decimals as %).
- Do not compute a winner or a joint decision in the UI; Phase 8 will define a supervised comparison.

## 11. Limitations and pending items for Phase 8

- **Synthetic, undated data:** a single undated fundamentals snapshot and synthetic prices. The results are illustrative only.
- **ARGO is limited:** it is a P/E lens; real value analysis needs the dataset extension above.
- **AEGIS is single-symbol:** it has no portfolio context (diversification, concentration, liquidity).
- **Phase 8:** a supervised committee comparison with explicit rules for weighing disagreement, built on these evaluations without changing them. It must never trigger orders.
