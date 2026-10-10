import type { BrokerStatus, Proposal } from "./types";

export const PAPER_NOTICE = "Paper Trading — dinero ficticio";
const finalStatuses = new Set<BrokerStatus>(["filled", "canceled", "expired", "rejected"]);
export const isFinalOrder = (status: BrokerStatus | null) => status !== null && finalStatuses.has(status);

export function canConfirm(proposal: Proposal, now = Date.now()): boolean {
  const expires = Date.parse(proposal.expiresAt);
  return proposal.status === "open" && Number.isFinite(expires) && now < expires &&
    ["not_submitted", "failed_before_submit"].includes(proposal.submissionStatus);
}

/** Scheduling decision only. Never calls confirm or cancel. */
export function nextStatusRead(proposal: Proposal):
  { kind: "order"; id: string } | { kind: "reconcile"; id: string } | null {
  if (proposal.status === "expired" || proposal.submissionStatus === "rejected_by_broker") return null;
  if (proposal.submissionStatus === "submitting") return { kind: "reconcile", id: proposal.id };
  if (isFinalOrder(proposal.brokerStatus)) return null;
  if (proposal.brokerOrderId) return { kind: "order", id: proposal.brokerOrderId };
  if (proposal.submissionStatus === "submission_unknown") return { kind: "reconcile", id: proposal.id };
  return null;
}

export function canCancel(proposal: Proposal): boolean {
  return proposal.submissionStatus === "submitted" && Boolean(proposal.brokerOrderId) &&
    !isFinalOrder(proposal.brokerStatus) && proposal.brokerStatus !== "pending_cancel";
}
