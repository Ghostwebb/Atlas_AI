import { ReactNode } from "react";
import { TONE_BAR, TONE_CHIP, UNAVAILABLE_TEXT, labelTone, scoreToBarPercent } from "@/lib/format";

export interface Metric {
  label: string;
  value: string;
}

interface AnalysisPanelProps {
  title: string;
  description: string;
  label: string | undefined;
  score: number | null | undefined;
  // "signed": score in [-1, 1] drawn centered. "unit": already 0..1 (risk score).
  scale?: "signed" | "unit";
  metrics: Metric[];
  children?: ReactNode;
}

export function AnalysisPanel({
  title,
  description,
  label,
  score,
  scale = "signed",
  metrics,
  children,
}: AnalysisPanelProps) {
  const isUnavailable = !label || label === "unavailable";
  const tone = labelTone(label);
  const barPercent =
    score === null || score === undefined
      ? 0
      : scale === "unit"
        ? Math.max(0, Math.min(100, score * 100))
        : scoreToBarPercent(score);

  return (
    <section className="flex flex-col rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">{title}</h3>
          <p className="mt-0.5 text-xs text-zinc-500">{description}</p>
        </div>
        <span
          className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium capitalize ring-1 ${TONE_CHIP[tone]}`}
        >
          {isUnavailable ? UNAVAILABLE_TEXT : label}
        </span>
      </div>

      {!isUnavailable && (
        <div className="mt-4" aria-label={`${title} score`}>
          <div className="flex justify-between text-[11px] text-zinc-500">
            <span>{scale === "unit" ? "Lower" : "−1"}</span>
            <span>
              Score{" "}
              {score === null || score === undefined
                ? UNAVAILABLE_TEXT
                : score.toFixed(2)}
            </span>
            <span>{scale === "unit" ? "Higher" : "+1"}</span>
          </div>
          <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-zinc-800">
            {scale === "signed" && (
              <div className="absolute left-1/2 top-0 h-full w-px bg-zinc-600" />
            )}
            <div
              className={`h-full rounded-full transition-all duration-500 ${TONE_BAR[tone]}`}
              style={{ width: `${barPercent}%` }}
            />
          </div>
        </div>
      )}

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {metrics.map((metric) => (
          <div key={metric.label} className="flex flex-col">
            <dt className="text-[11px] uppercase tracking-wide text-zinc-500">{metric.label}</dt>
            <dd
              className={`font-mono text-sm ${
                metric.value === UNAVAILABLE_TEXT ? "text-zinc-500 italic" : "text-zinc-100"
              }`}
            >
              {metric.value}
            </dd>
          </div>
        ))}
      </dl>

      {children}
    </section>
  );
}
