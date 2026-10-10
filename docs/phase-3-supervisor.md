# Phase 3: deterministic supervisor

The supervisor reads the finished analysis and the dataset facts. It does not query the
data provider and does not recompute indicators. It is pure rules, runs offline, and
produces the same output for the same input.

Schema version: `1.1`. Policy version: `phase3-v2`. All thresholds live in
`backend/app/supervision/config.py`. Changing a value means bumping `POLICY_VERSION`.

## Changes after the PR #1 review (schema 1.0 → 1.1, policy phase3-v1 → phase3-v2)

| Defect | Fix |
|---|---|
| The trend narrative inferred "20-day above 50-day" from the `bullish` label. The engine score also weighs price vs SMA20, so `bullish` can coexist with SMA20 < SMA50. | The narrative compares the published averages (`above` / `below` / `equal to`) and cites them. It also states the price vs the 20-day average. Windows come from `SHORT_MA_WINDOW` / `LONG_MA_WINDOW`. Missing metrics are omitted, never shown as zero, and an available trend without averages is an integrity error. |
| `HISTORY_INSUFFICIENT` cited `dataset.*`, which only existed in an internal validation view and never reached the client. | Refs now point to `supervision.dataQuality.historicalObservations` / `requiredHistoricalObservations`. Validation runs against the JSON-mode public response plus its own serialized `supervision` block; no internal object is added. `requiredHistoricalObservations` comes from the same `DatasetInfo.requiredObservations` the rules use, and a mismatch with the engine's `MIN_BARS_REQUIRED` is an integrity error. |
| `supportingEvidence` / `opposingEvidence` encoded market polarity, so a SELL had empty `keyReasons` (TSLA). | Polarity and relation to the recommendation are now separate (policy below). `keyReasons` justify the emitted recommendation. |
| Report text said "synthetic demo data" unconditionally. | Provenance wording is derived from `dataQuality.provenance`. Evidence, findings and limitations no longer mention provenance. |

Additive fields: `EvidenceItem.polarity`, `SupervisionReport.neutralEvidence`,
`Report.counterpoints`. Semantic change: `direction`, `supportingEvidence` and
`opposingEvidence` are now relative to the recommendation. Neutral and risk-context
signals, previously dropped, are kept in `neutralEvidence`.

## Rules and thresholds

| Rule | Condition | Category / severity |
|------|-----------|---------------------|
| `MOMENTUM_TREND_DIVERGENCE` | Momentum and trend scores point in opposite directions, each with \|score\| ≥ 0.20 | contradiction / warning |
| `TECHNICAL_FUNDAMENTAL_DIVERGENCE` | Technical composite ≥ +0.20 and fundamentals ≤ −0.20, or the reverse. Technical composite = (0.3·momentum + 0.3·trend) / 0.6 | contradiction / warning |
| `OPPORTUNITY_RISK_CONFLICT` | Engine recommendation is BUY and risk label is `high` | caution / warning |
| `HISTORY_INSUFFICIENT` | Fewer observations than `requiredHistoricalObservations` (50) | data gap / warning |
| `FUNDAMENTALS_MISSING` | 0 of 4 fundamental metrics available | data gap / info |
| `FUNDAMENTALS_PARTIAL` | 1–3 of 4 fundamental metrics available | data gap / info |
| `LOW_CONFIDENCE` | Confidence < 0.50, only when no contradiction or caution finding exists | observation / info |

- The direction threshold is inclusive at 0.20. Scores with |score| < 0.20 are neutral.
- A missing component never counts as positive or negative evidence.

## Evidence policy (phase3-v2)

**Polarity** (`EvidenceItem.polarity`) is the market reading of a signal, independent of the
recommendation: positive momentum/fundamentals and a bullish trend are `favorable`; negative
and bearish are `unfavorable`. For risk: low is `favorable`, high is `unfavorable`, moderate
is `neutral`.

**Direction** (`EvidenceItem.direction`, and the list the item is in) is the relation to the
engine recommendation.

Directional components (momentum, trend, fundamental):

| Recommendation | Favorable | Unfavorable | Neutral |
|---|---|---|---|
| BUY | supporting | opposing | neutral |
| SELL | opposing | supporting | neutral |
| HOLD | see below | see below | supporting |

HOLD means the engine composite fell inside the ±0.25 band. Neutral signals support it.
If favorable and unfavorable signals are both present, they offset each other, so all of
them are `supporting`, and `keyReasons` starts with an explicit offset sentence. If only one
polarity is present, those signals lean away from a neutral stance and are `opposing`.

Risk describes historical volatility and drawdown. It is not a direction:

| Recommendation | Low | Moderate | High |
|---|---|---|---|
| BUY | supporting | neutral | opposing (plus the `OPPORTUNITY_RISK_CONFLICT` warning) |
| HOLD | neutral | neutral | neutral |
| SELL | neutral | neutral | neutral |

High risk is never a reason to sell, and low risk is never evidence against selling. SELL is
the engine's label for an unfavorable reading; it never means opening a short position.
High risk always appears in `report.riskFactors`, whatever the recommendation.

Each available component appears in exactly one of the three lists, in the fixed order
momentum, trend, risk, fundamental.

## Status

Precedence: `insufficient_data` > `caution` > `consistent`.

- `insufficient_data`: history is below the requirement, or a core technical component is missing.
- `caution`: at least one contradiction or caution finding exists.
- `consistent`: no contradiction or caution findings. Observations do not change the status.

## Data quality

- `componentCoverage` = available components / 4. `fundamentalCoverage` = metrics used / 4.
- `label`: `insufficient` when the status is `insufficient_data`; `limited` when any coverage is
  below 1.0; otherwise `sufficient`.
- `provenance` comes from the data source map. An unmapped source or a mismatched provenance
  is an integrity error (HTTP 500, error contract, no report).

## Confidence

The engine's `confidence` is `coverage × agreement` (agreement = 1 − population standard
deviation of the component scores). It measures data coverage and signal agreement, not a
probability. The supervisor reports it and never changes it.

## Integrity and references

Every reference in `findings[].evidenceRefs` and in the three evidence lists is a dotted path
that resolves in the final HTTP JSON (for example `analysis.trend.shortMovingAverage` or
`supervision.dataQuality.historicalObservations`). Every metric quoted in a description has a
reference. If any reference does not resolve, the supervisor raises an integrity error and the
API returns 500 with the error contract.

## Guidance for the frontend (Codex)

- **Status badge:** `supervision.status`. **Headline and summary:** `supervision.report`.
- **`keyReasons`:** reasons that support the emitted recommendation. Show them as "why".
  For a HOLD, the first line may explain that favorable and unfavorable signals offset.
- **`counterpoints`:** signals pointing against the recommendation. Show them separately from
  risks. Risk is never a counterpoint.
- **`riskFactors`:** high historical risk plus contradiction and caution findings.
- **`dataGaps`:** missing history, missing components and missing fundamentals.
- **Evidence lists:** use `direction` for grouping and `polarity` for color
  (favorable / unfavorable / neutral). Do not color by list: in a SELL, supporting items are
  unfavorable signals.
- **References:** each `refs` / `evidenceRefs` entry is a path into the same response; use it
  to highlight the cited metric.
- **Provenance:** read `supervision.dataQuality.provenance`. When it is `synthetic`, always show
  the synthetic-data notice and the `limitations` list. Never label synthetic data as market data.
- **Errors:** 500 with `{error, message}` means the supervisor refused the analysis; show the
  error state.

## Examples (synthetic demo data; real backend output)

All values below come from the synthetic `demo_dataset` or a hand-built synthetic fixture.
They are not market data.

### NVDA, BUY (full supervision block)

```json
{
  "schemaVersion": "1.1",
  "policyVersion": "phase3-v2",
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
      "polarity": "favorable",
      "direction": "supporting",
      "description": "Momentum is positive (+53.4% over the analysis period).",
      "refs": [
        "signals.momentum",
        "analysis.momentum.score",
        "analysis.momentum.changePercent"
      ]
    },
    {
      "component": "trend",
      "polarity": "favorable",
      "direction": "supporting",
      "description": "Trend is bullish. The 20-day average (252.14) is above the 50-day average (209.91). The price is 9.5% above the 20-day average.",
      "refs": [
        "signals.trend",
        "analysis.trend.score",
        "analysis.trend.shortMovingAverage",
        "analysis.trend.longMovingAverage",
        "analysis.trend.priceVsShortMovingAverage"
      ]
    },
    {
      "component": "fundamental",
      "polarity": "favorable",
      "direction": "supporting",
      "description": "Fundamentals are positive based on 4 of 4 metrics.",
      "refs": [
        "signals.fundamental",
        "analysis.fundamental.score",
        "analysis.fundamental.metricsUsed",
        "supervision.dataQuality.expectedFundamentalMetrics"
      ]
    }
  ],
  "opposingEvidence": [
    {
      "component": "risk",
      "polarity": "unfavorable",
      "direction": "opposing",
      "description": "Historical risk is high (annualized volatility 49%, maximum drawdown 24%).",
      "refs": [
        "signals.risk",
        "analysis.risk.score",
        "analysis.risk.volatility",
        "analysis.risk.maxDrawdown"
      ]
    }
  ],
  "neutralEvidence": [],
  "limitations": [
    {
      "code": "SYNTHETIC_DATA",
      "message": "Prices and fundamentals come from a synthetic demo dataset."
    },
    {
      "code": "NON_PREDICTIVE",
      "message": "Rules and thresholds are educational. They describe past data and do not predict returns."
    }
  ],
  "report": {
    "headline": "Favorable demo signals with conflicts that require caution",
    "summary": "Engine recommendation BUY on synthetic demo data. Supervisor status: caution. 1 finding(s): 1 warning(s), 0 informational. Results describe the synthetic demo dataset, not real market prices.",
    "keyReasons": [
      "Momentum is positive (+53.4% over the analysis period).",
      "Trend is bullish. The 20-day average (252.14) is above the 50-day average (209.91). The price is 9.5% above the 20-day average.",
      "Fundamentals are positive based on 4 of 4 metrics."
    ],
    "counterpoints": [],
    "riskFactors": [
      "Historical risk is high (annualized volatility 49%, maximum drawdown 24%).",
      "The engine recommendation is BUY while historical risk is high. This is a conflict between favorable signals and risk, not a statement that the recommendation is wrong."
    ],
    "dataGaps": []
  }
}
```

### TSLA, SELL (negative signals are the reasons; high risk is a risk factor)

```json
{
  "status": "consistent",
  "engineRecommendation": "SELL",
  "findings": [],
  "evidence": {
    "supportingEvidence": [
      "momentum (unfavorable)",
      "trend (unfavorable)",
      "fundamental (unfavorable)"
    ],
    "opposingEvidence": [],
    "neutralEvidence": [
      "risk (unfavorable)"
    ]
  },
  "report": {
    "headline": "Unfavorable demo signals, internally consistent",
    "summary": "Engine recommendation SELL on synthetic demo data. Supervisor status: consistent. 0 finding(s): 0 warning(s), 0 informational. Results describe the synthetic demo dataset, not real market prices.",
    "keyReasons": [
      "Momentum is negative (-39.1% over the analysis period).",
      "Trend is bearish. The 20-day average (178.92) is below the 50-day average (186.31). The price is 14.9% below the 20-day average.",
      "Fundamentals are negative based on 4 of 4 metrics."
    ],
    "counterpoints": [],
    "riskFactors": [
      "Historical risk is high (annualized volatility 63%, maximum drawdown 52%)."
    ],
    "dataGaps": []
  }
}
```

### AAPL, HOLD with offsetting signals

```json
{
  "status": "caution",
  "engineRecommendation": "HOLD",
  "findings": [
    {
      "ruleId": "TECHNICAL_FUNDAMENTAL_DIVERGENCE",
      "evidenceRefs": [
        "analysis.trend.score",
        "analysis.momentum.score",
        "analysis.fundamental.score"
      ]
    }
  ],
  "evidence": {
    "supportingEvidence": [
      "momentum (neutral)",
      "trend (unfavorable)",
      "fundamental (favorable)"
    ],
    "opposingEvidence": [],
    "neutralEvidence": [
      "risk (neutral)"
    ]
  },
  "report": {
    "headline": "Mixed or neutral demo signals with conflicts that require caution",
    "summary": "Engine recommendation HOLD on synthetic demo data. Supervisor status: caution. 1 finding(s): 1 warning(s), 0 informational. Results describe the synthetic demo dataset, not real market prices.",
    "keyReasons": [
      "Favorable signals (fundamental) and unfavorable signals (trend) offset each other.",
      "Momentum is neutral (+0.4% over the analysis period).",
      "Trend is bearish. The 20-day average (192.40) is below the 50-day average (208.68). The price is 0.9% below the 20-day average.",
      "Fundamentals are positive based on 4 of 4 metrics."
    ],
    "counterpoints": [],
    "riskFactors": [
      "The technical block is unfavorable while the fundamentals are favorable."
    ],
    "dataGaps": []
  }
}
```

### Insufficient history (30 bars, controlled synthetic fixture via `FixedProvider`)

```json
{
  "status": "insufficient_data",
  "engineRecommendation": "BUY",
  "findings": [
    {
      "ruleId": "HISTORY_INSUFFICIENT",
      "evidenceRefs": [
        "supervision.dataQuality.historicalObservations",
        "supervision.dataQuality.requiredHistoricalObservations"
      ]
    }
  ],
  "evidence": {
    "supportingEvidence": [
      "momentum (favorable)",
      "risk (favorable)",
      "fundamental (favorable)"
    ],
    "opposingEvidence": [],
    "neutralEvidence": []
  },
  "report": {
    "headline": "Insufficient evidence for a reliable demo report",
    "summary": "Engine recommendation BUY on synthetic demo data. Supervisor status: insufficient_data. 1 finding(s): 1 warning(s), 0 informational. Results describe the synthetic demo dataset, not real market prices.",
    "keyReasons": [
      "Momentum is positive (+29.0% over the analysis period).",
      "Historical risk is low (annualized volatility 1%, maximum drawdown 0%).",
      "Fundamentals are positive based on 4 of 4 metrics."
    ],
    "counterpoints": [],
    "riskFactors": [],
    "dataGaps": [
      "30 observations are available; 50 are required for the technical indicators.",
      "Components without data: trend."
    ]
  },
  "dataQuality": {
    "label": "insufficient",
    "historicalObservations": 30,
    "requiredHistoricalObservations": 50,
    "missingComponents": [
      "trend"
    ],
    "provenance": "synthetic"
  }
}
```

Both `HISTORY_INSUFFICIENT` refs resolve in the HTTP response at
`supervision.dataQuality.historicalObservations` (30) and
`supervision.dataQuality.requiredHistoricalObservations` (50).

## Limitations

- Rules are educational. They describe past data and do not predict returns.
- Thresholds are not calibrated or backtested.
- Only the demo dataset is supported in this phase.
- Frontend visual validation of the supervision panel is pending.
