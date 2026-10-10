import type { AnalyzeResponse, Recommendation } from "@/lib/types";
import {
  UNAVAILABLE_TEXT,
  formatFraction,
  formatNumber,
  formatSignedPercent,
} from "@/lib/format";
import { AnalysisPanel, type Metric } from "./AnalysisPanel";

const RECOMMENDATION_STYLES: Record<Recommendation, string> = {
  BUY: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  HOLD: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  SELL: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const RECOMMENDATION_NOTE: Record<Recommendation, string> = {
  BUY: "Positive composite signal on the demo data.",
  HOLD: "Mixed or neutral composite signal on the demo data.",
  SELL: "Negative composite signal on the demo data.",
};

function formatAsOf(value: string | null | undefined): string {
  if (!value) return UNAVAILABLE_TEXT;
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function ResultCard({ result }: { result: AnalyzeResponse }) {
  // Tolerates partial payloads: every block is optional and missing values show "Data unavailable".
  const analysis = result.analysis ?? {};
  const momentum = analysis.momentum;
  const trend = analysis.trend;
  const risk = analysis.risk;
  const fundamental = analysis.fundamental;

  const confidencePct = Math.round((result.confidence ?? 0) * 100);
  const recommendation = result.recommendation;

  const momentumMetrics: Metric[] = [
    { label: "Period change", value: formatSignedPercent(momentum?.changePercent) },
  ];

  const trendMetrics: Metric[] = [
    { label: "SMA 20", value: formatNumber(trend?.shortMovingAverage) },
    { label: "SMA 50", value: formatNumber(trend?.longMovingAverage) },
    { label: "Price vs SMA 20", value: formatFraction(trend?.priceVsShortMovingAverage) },
    { label: "Price vs SMA 50", value: formatFraction(trend?.priceVsLongMovingAverage) },
  ];

  const riskMetrics: Metric[] = [
    { label: "Annual volatility", value: formatFraction(risk?.volatility) },
    { label: "Max drawdown", value: formatFraction(risk?.maxDrawdown) },
  ];

  const fundamentalMetrics: Metric[] = [
    { label: "Revenue growth", value: formatFraction(fundamental?.revenueGrowth) },
    { label: "Profit margin", value: formatFraction(fundamental?.profitMargin) },
    {
      label: "P/E ratio",
      value: fundamental?.peRatio == null ? UNAVAILABLE_TEXT : formatNumber(fundamental.peRatio, 1),
    },
    { label: "Earnings growth", value: formatFraction(fundamental?.earningsGrowth) },
  ];

  return (
    <article className="space-y-6">
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 sm:p-8">
        <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs font-medium text-amber-200">
          SIMULATED DATA — synthetic demo dataset, not real market data. Data as of{" "}
          {formatAsOf(result.dataAsOf)}.
        </div>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="font-mono text-sm text-zinc-500">{result.symbol}</p>
            <h2 className="text-2xl font-semibold tracking-tight">{result.companyName}</h2>
          </div>
          <div className="text-right">
            <span
              className={`inline-block rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ${
                RECOMMENDATION_STYLES[recommendation] ?? RECOMMENDATION_STYLES.HOLD
              }`}
            >
              {recommendation}
            </span>
            <p className="mt-2 max-w-xs text-xs text-zinc-500">
              {RECOMMENDATION_NOTE[recommendation] ?? ""}
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-[1fr_2fr]">
          <div className="rounded-lg border border-[var(--border)] p-4">
            <p className="text-xs uppercase tracking-wide text-zinc-500">Confidence</p>
            <p className="mt-1 text-3xl font-semibold">{confidencePct}%</p>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-zinc-800">
              <div
                className="h-full rounded-full bg-gradient-to-r from-violet-500 to-blue-500"
                style={{ width: `${confidencePct}%` }}
              />
            </div>
            <p className="mt-2 text-[11px] leading-snug text-zinc-500">
              Data coverage × signal agreement. Not a probability of success.
            </p>
          </div>
          <div className="rounded-lg border border-[var(--border)] p-4">
            <p className="text-xs uppercase tracking-wide text-zinc-500">Summary</p>
            <p className="mt-1 text-sm text-zinc-200">{result.summary}</p>
          </div>
        </div>
      </div>

      <div>
        <p className="mb-3 text-xs uppercase tracking-wide text-zinc-500">Analyzers</p>
        <div className="grid gap-4 md:grid-cols-2">
          <AnalysisPanel
            title="Momentum"
            description="Price change over the demo period"
            label={result.signals?.momentum ?? momentum?.label}
            score={momentum?.score}
            metrics={momentumMetrics}
          />
          <AnalysisPanel
            title="Trend"
            description="20-day vs 50-day moving averages"
            label={result.signals?.trend ?? trend?.label}
            score={trend?.score}
            metrics={trendMetrics}
          />
          <AnalysisPanel
            title="Risk"
            description="Historical volatility and drawdown (educational)"
            label={result.signals?.risk ?? risk?.label}
            score={risk?.score}
            scale="unit"
            metrics={riskMetrics}
          />
          <AnalysisPanel
            title="Fundamentals"
            description={`Demo metrics (${fundamental?.metricsUsed ?? 0} of 4 available)`}
            label={result.signals?.fundamental ?? fundamental?.label}
            score={fundamental?.score}
            metrics={fundamentalMetrics}
          />
        </div>
      </div>

      {result.explanation && result.explanation.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
          <p className="text-xs uppercase tracking-wide text-zinc-500">Why this result</p>
          <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-zinc-300 marker:text-zinc-600">
            {result.explanation.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ol>
          {result.dataIssues && result.dataIssues.length > 0 && (
            <p className="mt-4 text-xs text-amber-300">
              Data quality warnings: {result.dataIssues.join("; ")}
            </p>
          )}
        </div>
      )}
    </article>
  );
}
