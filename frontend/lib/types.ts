// Mirrors the API contract defined in backend/app/schemas.py.

export type Recommendation = "BUY" | "HOLD" | "SELL";

export interface Signals {
  momentum: "positive" | "neutral" | "negative";
  risk: "low" | "moderate" | "high";
  trend: "positive" | "neutral" | "negative";
}

export interface AnalyzeResponse {
  symbol: string;
  companyName: string;
  recommendation: Recommendation;
  confidence: number;
  summary: string;
  signals: Signals;
  isSimulated: true;
}

export interface ErrorResponse {
  error: string;
  message: string;
}
