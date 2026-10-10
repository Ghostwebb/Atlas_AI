/** Decimal strings are preserved verbatim; never use floating-point arithmetic for orders. */
export type DecimalString = string;
export type SubmissionStatus = "not_submitted" | "submitting" | "submitted" | "submission_unknown" | "rejected_by_broker" | "failed_before_submit";
export type BrokerStatus = "new" | "partially_filled" | "filled" | "done_for_day" | "canceled" | "expired" | "replaced" | "pending_cancel" | "pending_replace" | "accepted" | "pending_new" | "accepted_for_bidding" | "stopped" | "rejected" | "suspended" | "calculated" | "unrecognized";
export type ProposalRequest = { symbol: string; analysisReference?: string } & (
  { side: "buy"; notional: DecimalString; qty?: never } |
  { side: "sell"; qty: DecimalString; notional?: never }
);
export interface Reservation {
  resourceType: "cash" | "shares"; symbol: string | null; amount: DecimalString;
  consumed: DecimalString; state: "held" | "acknowledged" | "released";
  releaseReason: "not_sent" | "broker_rejected" | "order_terminal" | null;
  filledQty: DecimalString; filledNotional: DecimalString;
}
export interface Proposal {
  id: string; environment: "paper"; symbol: string; side: "buy" | "sell";
  notional: DecimalString | null; qty: DecimalString | null; orderType: "market"; timeInForce: "day";
  clientOrderId: string; analysisReference: string | null; createdAt: string; expiresAt: string;
  status: "open" | "confirmed" | "expired"; submissionStatus: SubmissionStatus;
  brokerOrderId: string | null; brokerStatus: BrokerStatus | null;
  filledQty: DecimalString | null; filledAvgPrice: DecimalString | null; lastErrorCode: string | null;
  checks: { name: string; passed: boolean; detail: string }[]; warnings: string[];
  updatedAt: string; reservation: Reservation | null;
}
export interface BrokerOrder {
  id: string; clientOrderId: string; symbol: string; side: string; type: string; timeInForce: string;
  qty: DecimalString | null; notional: DecimalString | null; filledQty: DecimalString | null;
  filledAvgPrice: DecimalString | null; status: BrokerStatus; brokerStatusRaw: string;
  submittedAt: string | null; filledAt: string | null; canceledAt: string | null;
  proposalId: string | null; environment: "paper";
}
export interface Account {
  environment: "paper"; status: string; currency: string; cash: DecimalString | null;
  buyingPower: DecimalString | null; nonMarginableBuyingPower: DecimalString | null;
  equity: DecimalString | null; tradingBlocked: boolean; accountBlocked: boolean;
}
export interface Position {
  environment: "paper"; symbol: string; side: string; qty: DecimalString;
  qtyAvailable: DecimalString | null; avgEntryPrice: DecimalString | null;
  marketValue: DecimalString | null; assetClass: string | null;
}
export interface Clock { isOpen: boolean; timestamp: string | null; nextOpen: string | null; nextClose: string | null }
export interface PaperStatus {
  environment: "paper"; enabled: boolean; configured: boolean; brokerReachable: boolean | null;
  marketOpen: boolean | null; maxOrderNotionalUsd: DecimalString; proposalTtlSeconds: number;
  analysisDataNotice: string; message: string;
}
