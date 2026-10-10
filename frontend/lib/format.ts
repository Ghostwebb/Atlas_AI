// Display helpers. Missing values render as "Data unavailable", never as 0.

export const UNAVAILABLE_TEXT = "Data unavailable";

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE_TEXT;
  return `${value.toFixed(digits)}%`;
}

// Input is a decimal fraction (0.12 -> "12.0%").
export function formatFraction(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE_TEXT;
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatSignedPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE_TEXT;
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE_TEXT;
  return value.toFixed(digits);
}

// Score in [-1, 1] -> bar position in [0, 100].
export function scoreToBarPercent(score: number | null | undefined): number {
  if (score === null || score === undefined || Number.isNaN(score)) return 0;
  return Math.max(0, Math.min(100, ((score + 1) / 2) * 100));
}

// Labels arrive as plain strings; anything unrecognized is shown neutrally.
export function labelTone(label: string | undefined): "good" | "bad" | "warn" | "muted" {
  switch (label) {
    case "positive":
    case "bullish":
    case "low":
      return "good";
    case "negative":
    case "bearish":
    case "high":
      return "bad";
    case "neutral":
    case "moderate":
      return "warn";
    default:
      return "muted";
  }
}

export const TONE_CHIP: Record<ReturnType<typeof labelTone>, string> = {
  good: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  bad: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  warn: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  muted: "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30",
};

export const TONE_BAR: Record<ReturnType<typeof labelTone>, string> = {
  good: "bg-emerald-500",
  bad: "bg-rose-500",
  warn: "bg-amber-500",
  muted: "bg-zinc-600",
};
