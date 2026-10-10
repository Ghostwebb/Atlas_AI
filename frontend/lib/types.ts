// Mirrors the API contract defined in backend/app/schemas.py (Phase 2).
// Phase 2 fields are optional here so an older Phase 1 backend still renders.

export type Recommendation = "BUY" | "HOLD" | "SELL";

export type MomentumLabel = "positive" | "neutral" | "negative" | "unavailable";
export type TrendLabel = "bullish" | "neutral" | "bearish" | "unavailable";
export type RiskLabel = "low" | "moderate" | "high" | "unavailable";
export type FundamentalLabel = "positive" | "neutral" | "negative" | "unavailable";

export interface Signals {
  momentum: MomentumLabel | string;
  risk: RiskLabel | string;
  trend: TrendLabel | string;
  fundamental?: FundamentalLabel | string;
}

export interface MomentumAnalysis {
  label: MomentumLabel;
  score: number | null;
  changePercent: number | null;
}

export interface TrendAnalysis {
  label: TrendLabel;
  score: number | null;
  shortMovingAverage: number | null;
  longMovingAverage: number | null;
  priceVsShortMovingAverage: number | null;
  priceVsLongMovingAverage: number | null;
}

export interface RiskAnalysis {
  label: RiskLabel;
  score: number | null;
  volatility: number | null;
  maxDrawdown: number | null;
}

export interface FundamentalAnalysis {
  label: FundamentalLabel;
  score: number | null;
  metricsUsed: number;
  revenueGrowth: number | null;
  profitMargin: number | null;
  peRatio: number | null;
  earningsGrowth: number | null;
}

export interface AnalysisDetails {
  momentum?: MomentumAnalysis;
  trend?: TrendAnalysis;
  risk?: RiskAnalysis;
  fundamental?: FundamentalAnalysis;
}

export interface AnalyzeResponse {
  symbol: string;
  companyName: string;
  recommendation: Recommendation;
  confidence: number;
  summary: string;
  explanation?: string[];
  signals: Signals;
  analysis?: AnalysisDetails;
  isSimulated: true;
  dataSource?: string;
  dataAsOf?: string | null;
  dataIssues?: string[];
}

export interface ErrorResponse {
  error: string;
  message: string;
}
