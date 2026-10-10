# Phase 3: deterministic supervisor

The supervisor reads the finished analysis and the dataset facts. It does not query the
data provider and does not recompute indicators. It is pure rules, runs offline, and
produces the same output for the same input.

Policy version: `phase3-v1`. Schema version: `1.0`. All thresholds live in
`backend/app/supervision/config.py`. Changing a value means bumping `POLICY_VERSION`.

## Rules and thresholds

| Rule | Condition | Category / severity |
|------|-----------|---------------------|
| `MOMENTUM_TREND_DIVERGENCE` | Momentum and trend scores point in opposite directions, each with \|score\| ≥ 0.20 | contradiction / warning |
| `TECHNICAL_FUNDAMENTAL_DIVERGENCE` | Technical composite ≥ +0.20 and fundamentals ≤ −0.20, or the reverse. Technical composite = (0.3·momentum + 0.3·trend) / 0.6 | contradiction / warning |
| `OPPORTUNITY_RISK_CONFLICT` | Engine recommendation is BUY and risk label is `high` | caution / warning |
| `HISTORY_INSUFFICIENT` | Fewer than 50 observations (trend unavailable) | data gap / warning |
| `FUNDAMENTALS_MISSING` | 0 of 4 fundamental metrics available | data gap / info |
| `FUNDAMENTALS_PARTIAL` | 1–3 of 4 fundamental metrics available | data gap / info |
| `LOW_CONFIDENCE` | Confidence < 0.50, only when no contradiction or caution finding exists | observation / info |

- The direction threshold is inclusive at 0.20. Scores with |score| < 0.20 are neutral, so
  values near zero never create false conflicts.
- A missing component never counts as positive or negative evidence.

## Status

Precedence: `insufficient_data` > `caution` > `consistent`.

- `insufficient_data`: history is below the minimum, or a core technical component is missing.
- `caution`: at least one contradiction or caution finding exists.
- `consistent`: no contradiction or caution findings and enough evidence. Observations
  (for example `LOW_CONFIDENCE`) do not change the status.

## Data quality

- `componentCoverage` = available components / 4.
- `fundamentalCoverage` = metrics used / 4.
- `label`: `insufficient` when the status is `insufficient_data`; `limited` when any
  coverage is below 1.0; otherwise `sufficient`.
- `provenance` comes from the data source. Unmapped sources or mismatched provenance raise
  an integrity error and return HTTP 500 with the error contract. No report is produced.

## Confidence

The engine's `confidence` is `coverage × agreement`, where agreement = 1 − population
standard deviation of component scores. It measures data coverage and signal agreement. It
is not a probability. The supervisor reports it but does not change it.

## Report

The report is built from fixed templates and the findings. It has no timestamps, no news
text and no generated prose. `headline`, `summary`, `keyReasons`, `riskFactors` and
`dataGaps` are deterministic. The summary states that results describe synthetic demo data.

## API contract

`POST /api/analyze` keeps every Phase 2 field and adds `supervision` (always present on a
successful analysis). Frontend guidance:

- Use `supervision.status` for the badge. Use `supervision.report` for the text.
- `supportingEvidence` and `opposingEvidence` have `refs` such as `analysis.risk.volatility`.
  Each ref resolves to a field of the response. References beginning with `dataset.` point to
  the dataset facts (`observations`, `provenance`, and so on) and are validated server-side.
- `limitations` must be shown on screen. Always show the synthetic-data notice.
- `500` with `{error, message}` means the supervisor refused the analysis. Show the error state.

## Example (synthetic demo data, real output of the backend for NVDA)

The values below come from the `demo_dataset` (synthetic). They are not market data.

```json
{
  "schemaVersion": "1.0",
  "policyVersion": "phase3-v1",
  "status": "caution",
  "engineRecommendation": "BUY",
  "dataQuality": {
    "label": "sufficient",
    "componentCoverage": 1.0,
    "availableComponents": [
      "momentum",
      "trend",
      "risk",
      "fundamental"
    ],
    "missingComponents": [],
    "fundamentalCoverage": 1.0,
    "availableFundamentalMetrics": 4,
    "expectedFundamentalMetrics": 4,
    "historicalObservations": 120,
    "requiredHistoricalObservations": 50,
    "provenance": "synthetic",
    "firstDate": "2026-04-16",
    "lastDate": "2026-09-30"
  },
  "findings": [
    {
      "ruleId": "OPPORTUNITY_RISK_CONFLICT",
      "category": "caution",
      "severity": "warning",
      "title": "Favorable signal with high historical risk",
      "message": "The engine recommendation is BUY while historical risk is high. This is a conflict between favorable signals and risk, not a statement that the recommendation is wrong.",
      "evidenceRefs": [
        "recommendation",
        "signals.risk",
        "analysis.risk.score"
      ]
    }
  ],
  "supportingEvidence": [
    {
      "component": "momentum",
      "direction": "supporting",
      "description": "Momentum is positive (+53.4% over the demo period).",
      "refs": [
        "signals.momentum",
        "analysis.momentum.score",
        "analysis.momentum.changePercent"
      ]
    },
    {
      "component": "trend",
      "direction": "supporting",
      "description": "Trend is bullish: the 20-day average is above the 50-day average.",
      "refs": [
        "signals.trend",
        "analysis.trend.score"
      ]
    },
    {
      "component": "fundamental",
      "direction": "supporting",
      "description": "Fundamentals are positive based on 4 of 4 demo metrics.",
      "refs": [
        "signals.fundamental",
        "analysis.fundamental.score",
        "analysis.fundamental.metricsUsed"
      ]
    }
  ],
  "opposingEvidence": [
    {
      "component": "risk",
      "direction": "opposing",
      "description": "Risk is high (annualized volatility 49%, largest fall 24%).",
      "refs": [
        "signals.risk",
        "analysis.risk.score",
        "analysis.risk.volatility"
      ]
    }
  ],
  "limitations": [
    {
      "code": "SYNTHETIC_DATA",
      "message": "Prices and fundamentals come from a synthetic demo dataset."
    },
    {
      "code": "NON_PREDICTIVE",
      "message": "Rules and thresholds are educational. They describe past demo data and do not predict returns."
    }
  ],
  "report": {
    "headline": "Favorable demo signals with conflicts that require caution",
    "summary": "Engine recommendation BUY on synthetic demo data. Supervisor status: caution. 1 finding(s): 1 warning(s), 0 informational. Results describe the synthetic demo dataset, not real market prices.",
    "keyReasons": [
      "Momentum is positive (+53.4% over the demo period).",
      "Trend is bullish: the 20-day average is above the 50-day average.",
      "Fundamentals are positive based on 4 of 4 demo metrics."
    ],
    "riskFactors": [
      "Risk is high (annualized volatility 49%, largest fall 24%).",
      "The engine recommendation is BUY while historical risk is high. This is a conflict between favorable signals and risk, not a statement that the recommendation is wrong."
    ],
    "dataGaps": []
  }
}

```

## Limitations

- Rules are educational. They describe demo data and do not predict returns.
- Thresholds are not calibrated or backtested.
- Only the demo dataset is supported in this phase.
- Frontend visual validation of the supervision panel is pending.
