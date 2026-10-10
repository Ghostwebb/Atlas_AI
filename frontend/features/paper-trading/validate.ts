/**
 * Runtime validation of backend responses. A TypeScript cast does not validate HTTP data:
 * every field used to authorize an action is checked here. Malformed or contradictory data
 * throws INVALID_RESPONSE, which the controller treats as "unknown", never as permission.
 */
import { PaperApiError } from "./client";
import type { BrokerOrder, BrokerStatus, Proposal, ProposalRequest, Reservation, SubmissionStatus } from "./types";

const DECIMAL = /^\d{1,15}(\.\d{1,12})?$/;
const SUBMISSION: readonly SubmissionStatus[] = [
  "not_submitted", "submitting", "submitted", "submission_unknown", "rejected_by_broker", "failed_before_submit",
];
export const KNOWN_BROKER_STATUSES: readonly BrokerStatus[] = [
  "new", "partially_filled", "filled", "done_for_day", "canceled", "expired", "replaced", "pending_cancel",
  "pending_replace", "accepted", "pending_new", "accepted_for_bidding", "stopped", "rejected", "suspended",
  "calculated", "unrecognized",
];
const UNSENT: readonly SubmissionStatus[] = ["not_submitted", "failed_before_submit"];

function invalid(detail: string): never {
  throw new PaperApiError(`Respuesta inválida del backend (${detail}). No se habilita ninguna acción.`, "INVALID_RESPONSE");
}
type Obj = Record<string, unknown>;
const obj = (value: unknown, what: string): Obj =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as Obj : invalid(what);
const str = (o: Obj, key: string): string => {
  const v = o[key];
  return typeof v === "string" && v.length > 0 ? v : invalid(key);
};
const optStr = (o: Obj, key: string): string | null => (o[key] === null || o[key] === undefined ? null : str(o, key));
const decimal = (o: Obj, key: string): string => {
  const v = o[key];
  return typeof v === "string" && DECIMAL.test(v) ? v : invalid(key);
};
const optDecimal = (o: Obj, key: string): string | null => (o[key] === null || o[key] === undefined ? null : decimal(o, key));
function oneOf<T extends string>(o: Obj, key: string, values: readonly T[]): T {
  const v = o[key];
  return typeof v === "string" && (values as readonly string[]).includes(v) ? v as T : invalid(key);
}
const date = (o: Obj, key: string): string => {
  const v = str(o, key);
  return Number.isFinite(Date.parse(v)) ? v : invalid(key);
};

/** Unknown broker statuses are kept as "unrecognized": never final, never cancel-eligible by themselves. */
export function brokerStatus(value: unknown): BrokerStatus {
  return typeof value === "string" && (KNOWN_BROKER_STATUSES as readonly string[]).includes(value)
    ? value as BrokerStatus : "unrecognized";
}

function reservation(value: unknown): Reservation | null {
  if (value === null || value === undefined) return null;
  const r = obj(value, "reservation");
  return {
    resourceType: oneOf(r, "resourceType", ["cash", "shares"] as const),
    symbol: optStr(r, "symbol"),
    amount: decimal(r, "amount"),
    consumed: decimal(r, "consumed"),
    state: oneOf(r, "state", ["held", "acknowledged", "released"] as const),
    releaseReason: r.releaseReason === null || r.releaseReason === undefined ? null
      : oneOf(r, "releaseReason", ["not_sent", "broker_rejected", "order_terminal"] as const),
    filledQty: decimal(r, "filledQty"),
    filledNotional: decimal(r, "filledNotional"),
  };
}

export function parseProposal(value: unknown): Proposal {
  const p = obj(value, "proposal");
  if (p.environment !== "paper") invalid("environment");
  const status = oneOf(p, "status", ["open", "confirmed", "expired"] as const);
  const submissionStatus = oneOf(p, "submissionStatus", SUBMISSION);
  const side = oneOf(p, "side", ["buy", "sell"] as const);
  const brokerOrderId = optStr(p, "brokerOrderId");
  const notional = optDecimal(p, "notional");
  const qty = optDecimal(p, "qty");
  // Contradictions fail closed.
  if ((status === "open" || status === "expired") && !UNSENT.includes(submissionStatus)) invalid("status/submission");
  if (status === "confirmed" && UNSENT.includes(submissionStatus)) invalid("status/submission");
  if (submissionStatus === "submitted" && brokerOrderId === null) invalid("brokerOrderId");
  if (side === "buy" ? notional === null : qty === null) invalid("amount");
  if (!Array.isArray(p.checks) || !Array.isArray(p.warnings) || !p.warnings.every(w => typeof w === "string")) invalid("checks");
  const checks = p.checks.map(c => {
    const o = obj(c, "check");
    if (typeof o.passed !== "boolean" || typeof o.detail !== "string") invalid("check");
    return { name: str(o, "name"), passed: o.passed as boolean, detail: o.detail as string };
  });
  return {
    id: str(p, "id"), environment: "paper", symbol: str(p, "symbol"), side, notional, qty,
    orderType: oneOf(p, "orderType", ["market"] as const), timeInForce: oneOf(p, "timeInForce", ["day"] as const),
    clientOrderId: str(p, "clientOrderId"), analysisReference: optStr(p, "analysisReference"),
    createdAt: date(p, "createdAt"), expiresAt: date(p, "expiresAt"), status, submissionStatus,
    brokerOrderId, brokerStatus: p.brokerStatus === null || p.brokerStatus === undefined ? null : brokerStatus(p.brokerStatus),
    filledQty: optDecimal(p, "filledQty"), filledAvgPrice: optDecimal(p, "filledAvgPrice"),
    lastErrorCode: optStr(p, "lastErrorCode"), checks, warnings: p.warnings as string[],
    updatedAt: date(p, "updatedAt"), reservation: reservation(p.reservation),
  };
}

export function parseOrder(value: unknown): BrokerOrder {
  const o = obj(value, "order");
  if (o.environment !== "paper") invalid("environment");
  return {
    id: str(o, "id"), clientOrderId: str(o, "clientOrderId"), symbol: str(o, "symbol"),
    side: oneOf(o, "side", ["buy", "sell"] as const), type: typeof o.type === "string" ? o.type : "",
    timeInForce: typeof o.timeInForce === "string" ? o.timeInForce : "",
    qty: optDecimal(o, "qty"), notional: optDecimal(o, "notional"),
    filledQty: optDecimal(o, "filledQty"), filledAvgPrice: optDecimal(o, "filledAvgPrice"),
    status: brokerStatus(o.status), brokerStatusRaw: typeof o.brokerStatusRaw === "string" ? o.brokerStatusRaw : "",
    submittedAt: optStr(o, "submittedAt"), filledAt: optStr(o, "filledAt"), canceledAt: optStr(o, "canceledAt"),
    proposalId: optStr(o, "proposalId"), environment: "paper",
  };
}

export function parseCancel(value: unknown): { cancelRequested: true; order: BrokerOrder } {
  const c = obj(value, "cancel");
  if (c.cancelRequested !== true) invalid("cancelRequested");
  return { cancelRequested: true, order: parseOrder(c.order) };
}

/**
 * Builds the exact request body from user input. Only the documented fields are accepted:
 * analysis objects, recommendations or committee decisions are rejected, never converted.
 */
export function proposalRequest(input: unknown): ProposalRequest {
  const i = obj(input, "request");
  const allowed = new Set(["symbol", "side", "notional", "qty", "analysisReference"]);
  for (const key of Object.keys(i)) if (!allowed.has(key)) invalid(`campo no permitido: ${key}`);
  const symbol = str(i, "symbol");
  const analysisReference = optStr(i, "analysisReference");
  const ref = analysisReference === null ? {} : { analysisReference };
  if (i.side === "buy") {
    if (i.qty !== undefined) invalid("qty");
    return { symbol, side: "buy", notional: decimal(i, "notional"), ...ref };
  }
  if (i.side === "sell") {
    if (i.notional !== undefined) invalid("notional");
    return { symbol, side: "sell", qty: decimal(i, "qty"), ...ref };
  }
  return invalid("side");
}
