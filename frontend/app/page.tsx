"use client";

import { FormEvent, useState } from "react";
import { AnalyzeError, analyzeSymbol } from "@/lib/api";
import type { AnalyzeResponse, Recommendation, Signals } from "@/lib/types";

type ViewState =
  | { status: "idle" }
  | { status: "loading"; symbol: string }
  | { status: "success"; result: AnalyzeResponse }
  | { status: "error"; kind: "invalid_symbol" | "network" | "server"; message: string };

const RECOMMENDATION_STYLES: Record<Recommendation, string> = {
  BUY: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  HOLD: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  SELL: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const SIGNAL_LABELS: Record<keyof Signals, string> = {
  momentum: "Momentum",
  risk: "Risk",
  trend: "Trend",
};

export default function Home() {
  const [input, setInput] = useState("");
  const [view, setView] = useState<ViewState>({ status: "idle" });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const symbol = input.trim().toUpperCase();
    if (!symbol) {
      setView({
        status: "error",
        kind: "invalid_symbol",
        message: "Please enter a stock symbol, for example NVDA.",
      });
      return;
    }

    setView({ status: "loading", symbol });
    try {
      const result = await analyzeSymbol(symbol);
      setView({ status: "success", result });
    } catch (error) {
      const kind = error instanceof AnalyzeError ? error.kind : "server";
      const message =
        error instanceof Error ? error.message : "Something went wrong.";
      setView({ status: "error", kind, message });
    }
  }

  return (
    <div className="flex min-h-screen flex-1 flex-col">
      <header className="border-b border-[var(--border)] bg-[var(--surface)]/60 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="h-2.5 w-2.5 rounded-full bg-gradient-to-br from-violet-500 to-blue-500" />
            <span className="text-lg font-semibold tracking-tight">ATLAS AI</span>
          </div>
          <span className="text-xs text-zinc-500">
            Multi-Agent Investment Intelligence
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-12">
        <section>
          <h1 className="text-2xl font-semibold tracking-tight">Analyze a stock</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Enter a US stock symbol to run the analysis.
          </p>

          <form onSubmit={handleSubmit} className="mt-6 flex gap-3">
            <label htmlFor="symbol" className="sr-only">
              Stock symbol
            </label>
            <input
              id="symbol"
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="NVDA"
              autoComplete="off"
              maxLength={12}
              className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 font-mono text-base uppercase outline-none transition focus:border-violet-500 focus:ring-2 focus:ring-violet-500/30"
            />
            <button
              type="submit"
              disabled={view.status === "loading"}
              className="rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 px-6 py-3 text-sm font-medium transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {view.status === "loading" ? "Analyzing…" : "Analyze"}
            </button>
          </form>
        </section>

        <section className="mt-10" aria-live="polite">
          {view.status === "idle" && (
            <EmptyState />
          )}

          {view.status === "loading" && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8">
              <div className="flex items-center gap-3 text-sm text-zinc-300">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
                Running analysis for <span className="font-mono">{view.symbol}</span>…
              </div>
            </div>
          )}

          {view.status === "error" && (
            <div
              role="alert"
              className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-6 text-sm text-rose-200"
            >
              <p className="font-medium">
                {view.kind === "invalid_symbol"
                  ? "Invalid stock symbol"
                  : view.kind === "network"
                    ? "Backend unavailable"
                    : "Analysis failed"}
              </p>
              <p className="mt-1 text-rose-200/80">{view.message}</p>
            </div>
          )}

          {view.status === "success" && <ResultCard result={view.result} />}
        </section>
      </main>

      <footer className="border-t border-[var(--border)] px-6 py-4 text-center text-xs text-zinc-500">
        ATLAS AI is an analysis prototype. It does not provide investment advice or
        return guarantees.
      </footer>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed border-[var(--border)] p-10 text-center">
      <p className="text-sm text-zinc-400">
        Enter a symbol such as <span className="font-mono text-zinc-200">AAPL</span>,{" "}
        <span className="font-mono text-zinc-200">MSFT</span> or{" "}
        <span className="font-mono text-zinc-200">NVDA</span> to begin.
      </p>
    </div>
  );
}

function ResultCard({ result }: { result: AnalyzeResponse }) {
  const confidencePct = Math.round(result.confidence * 100);

  return (
    <article className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 sm:p-8">
      {result.isSimulated && (
        <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs font-medium text-amber-200">
          SIMULATED DATA — this is placeholder output for Phase 1, not real market data.
        </div>
      )}

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-zinc-500">{result.symbol}</p>
          <h2 className="text-2xl font-semibold tracking-tight">{result.companyName}</h2>
        </div>
        <span
          className={`rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ${RECOMMENDATION_STYLES[result.recommendation]}`}
        >
          {result.recommendation}
        </span>
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
        </div>
        <div className="rounded-lg border border-[var(--border)] p-4">
          <p className="text-xs uppercase tracking-wide text-zinc-500">Summary</p>
          <p className="mt-1 text-sm text-zinc-200">{result.summary}</p>
        </div>
      </div>

      <div className="mt-6">
        <p className="mb-3 text-xs uppercase tracking-wide text-zinc-500">Signals</p>
        <dl className="grid gap-3 sm:grid-cols-3">
          {(Object.keys(SIGNAL_LABELS) as (keyof Signals)[]).map((key) => (
            <div key={key} className="rounded-lg border border-[var(--border)] p-4">
              <dt className="text-xs text-zinc-500">{SIGNAL_LABELS[key]}</dt>
              <dd className="mt-1 text-sm font-medium capitalize text-zinc-100">
                {result.signals[key]}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </article>
  );
}
