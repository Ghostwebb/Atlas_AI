import type { AnalyzeResponse, ErrorResponse } from "./types";

// Backend base URL. Override with NEXT_PUBLIC_API_URL (see .env.example).
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class AnalyzeError extends Error {
  constructor(
    message: string,
    readonly kind: "invalid_symbol" | "network" | "server"
  ) {
    super(message);
    this.name = "AnalyzeError";
  }
}

export async function analyzeSymbol(symbol: string): Promise<AnalyzeResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    });
  } catch {
    throw new AnalyzeError(
      `Cannot reach the ATLAS AI backend at ${API_BASE_URL}. Is it running?`,
      "network"
    );
  }

  if (response.ok) {
    return (await response.json()) as AnalyzeResponse;
  }

  const body = (await response.json().catch(() => null)) as ErrorResponse | null;
  if (response.status === 400 || response.status === 404) {
    throw new AnalyzeError(
      body?.message ?? "Please provide a valid stock symbol.",
      "invalid_symbol"
    );
  }
  throw new AnalyzeError(
    body?.message ?? "The analysis service returned an unexpected error.",
    "server"
  );
}
