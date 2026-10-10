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

/**
 * Broker statuses that show the cancel button. Explicit allow-list: "not final" is NOT "cancelable".
 * Live orders still waiting for (more) execution. Everything else hides the button but keeps tracking:
 *   - unknown / missing (`unrecognized`, null), `pending_cancel`: not known to be cancelable;
 *   - `pending_replace`: Alpaca rejects cancels while replacing;
 *   - `done_for_day`, `replaced`, `stopped`, `suspended`, `calculated`: not a plain live ATLAS order;
 *   - `filled`, `canceled`, `expired`, `rejected`: final.
 * The backend can still answer ORDER_NOT_CANCELABLE (filled meanwhile) or 200 with `filled`.
 */
export const CANCELABLE_STATUSES: ReadonlySet<BrokerStatus> = new Set<BrokerStatus>([
  "new", "accepted", "pending_new", "accepted_for_bidding", "partially_filled",
]);

export function canCancel(proposal: Pick<Proposal, "submissionStatus" | "brokerOrderId" | "brokerStatus">): boolean {
  return proposal.submissionStatus === "submitted" && Boolean(proposal.brokerOrderId) &&
    proposal.brokerStatus !== null && proposal.brokerStatus !== undefined &&
    CANCELABLE_STATUSES.has(proposal.brokerStatus);
}
