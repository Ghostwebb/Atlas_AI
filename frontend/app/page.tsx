"use client";

import { FormEvent, useState } from "react";
import { AnalyzeError, analyzeSymbol } from "@/lib/api";
import type { AnalyzeResponse } from "@/lib/types";
import { ResultCard } from "@/components/ResultCard";

type ViewState =
  | { status: "idle" }
  | { status: "loading"; symbol: string }
  | { status: "success"; result: AnalyzeResponse }
  | { status: "error"; kind: "invalid_symbol" | "network" | "server"; message: string };

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
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="h-2.5 w-2.5 rounded-full bg-gradient-to-br from-violet-500 to-blue-500" />
            <span className="text-lg font-semibold tracking-tight">ATLAS AI</span>
          </div>
          <span className="text-xs text-zinc-500">
            Multi-Agent Investment Intelligence
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-12">
        <section>
          <h1 className="text-2xl font-semibold tracking-tight">Analyze a stock</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Enter a US stock symbol to run the analysis on the demo dataset.
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
              className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 font-mono text-base uppercase outline-none transition focus:border-violet-500 focus:ring-2 focus:ring-violet-500/30"
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
          {view.status === "idle" && <EmptyState />}

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
        ATLAS AI is an educational prototype running on synthetic demo data. It is not
        investment advice and does not guarantee returns.
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
