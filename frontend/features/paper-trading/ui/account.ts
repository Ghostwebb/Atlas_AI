/**
 * Read-only loading of feature status, market state, account and positions.
 * Responses are validated at runtime; a missing value stays null ("No disponible"), never 0.
 * There is no fixture fallback: if the backend fails, the screen says so.
 */
import { PaperApiError } from "../client";
import type { PaperClient } from "../controller";

const SIGNED_DECIMAL = /^-?\d{1,15}(\.\d{1,12})?$/;
type Obj = Record<string, unknown>;

function bad(what: string): never {
  throw new PaperApiError(`Respuesta inválida del backend (${what}).`, "INVALID_RESPONSE");
}
const asObj = (v: unknown, what: string): Obj =>
  v !== null && typeof v === "object" && !Array.isArray(v) ? v as Obj : bad(what);
const optBool = (o: Obj, k: string): boolean | null =>
  o[k] === null || o[k] === undefined ? null : typeof o[k] === "boolean" ? o[k] as boolean : bad(k);
const optDec = (o: Obj, k: string): string | null =>
  o[k] === null || o[k] === undefined ? null
    : typeof o[k] === "string" && SIGNED_DECIMAL.test(o[k] as string) ? o[k] as string : bad(k);
const optStr = (o: Obj, k: string): string | null =>
  o[k] === null || o[k] === undefined ? null : typeof o[k] === "string" ? o[k] as string : bad(k);

export interface StatusView {
  enabled: boolean; configured: boolean; brokerReachable: boolean | null; marketOpen: boolean | null;
  maxOrderNotionalUsd: string | null; proposalTtlSeconds: number | null; analysisDataNotice: string | null;
  message: string | null;
}
export interface AccountView {
  status: string | null; currency: string | null; cash: string | null; buyingPower: string | null;
  nonMarginableBuyingPower: string | null; equity: string | null;
  tradingBlocked: boolean | null; accountBlocked: boolean | null;
}
export interface PositionView {
  symbol: string; side: string | null; qty: string | null; qtyAvailable: string | null;
  avgEntryPrice: string | null; marketValue: string | null;
}

export function parseStatus(v: unknown): StatusView {
  const o = asObj(v, "status");
  if (o.environment !== "paper") bad("environment");
  if (typeof o.enabled !== "boolean" || typeof o.configured !== "boolean") bad("enabled/configured");
  return {
    enabled: o.enabled, configured: o.configured,
    brokerReachable: optBool(o, "brokerReachable"), marketOpen: optBool(o, "marketOpen"),
    maxOrderNotionalUsd: optDec(o, "maxOrderNotionalUsd"),
    proposalTtlSeconds: typeof o.proposalTtlSeconds === "number" ? o.proposalTtlSeconds : null,
    analysisDataNotice: optStr(o, "analysisDataNotice"), message: optStr(o, "message"),
  };
}

export function parseAccount(v: unknown): AccountView {
  const o = asObj(v, "account");
  if (o.environment !== "paper") bad("environment");
  return {
    status: optStr(o, "status"), currency: optStr(o, "currency"), cash: optDec(o, "cash"),
    buyingPower: optDec(o, "buyingPower"), nonMarginableBuyingPower: optDec(o, "nonMarginableBuyingPower"),
    equity: optDec(o, "equity"), tradingBlocked: optBool(o, "tradingBlocked"), accountBlocked: optBool(o, "accountBlocked"),
  };
}

export function parsePositions(v: unknown): PositionView[] {
  if (!Array.isArray(v)) bad("positions");
  return v.map(item => {
    const o = asObj(item, "position");
    if (o.environment !== "paper" || typeof o.symbol !== "string" || !o.symbol) bad("position");
    return {
      symbol: o.symbol as string, side: optStr(o, "side"), qty: optDec(o, "qty"), qtyAvailable: optDec(o, "qtyAvailable"),
      avgEntryPrice: optDec(o, "avgEntryPrice"), marketValue: optDec(o, "marketValue"),
    };
  });
}

export type Availability = "loading" | "unreachable" | "disabled" | "not_configured" | "broker_unreachable" | "available";

export function availabilityOf(status: StatusView | null, error: unknown): Availability {
  if (status === null) return error ? "unreachable" : "loading";
  if (!status.enabled) return "disabled";
  if (!status.configured) return "not_configured";
  if (status.brokerReachable === false) return "broker_unreachable";
  return "available";
}

export interface AccountSnapshot {
  status: StatusView | null; account: AccountView | null; positions: PositionView[] | null;
  nextOpen: string | null; statusError: PaperApiError | null; accountError: PaperApiError | null;
}

const asApiError = (e: unknown): PaperApiError =>
  e instanceof PaperApiError ? e : new PaperApiError("No se pudo leer el backend.", "NETWORK_ERROR");

/** One read of status (+ account, positions and clock when the feature is available). Never mutates. */
export async function loadAccount(client: PaperClient, signal: AbortSignal): Promise<AccountSnapshot> {
  const snapshot: AccountSnapshot = { status: null, account: null, positions: null, nextOpen: null,
    statusError: null, accountError: null };
  try {
    snapshot.status = parseStatus(await client.status(signal));
  } catch (error) {
    if (signal.aborted) throw error;
    snapshot.statusError = asApiError(error);
    return snapshot;
  }
  if (availabilityOf(snapshot.status, null) !== "available") return snapshot;
  try {
    const [account, positions] = await Promise.all([client.account(signal), client.positions(signal)]);
    snapshot.account = parseAccount(account);
    snapshot.positions = parsePositions(positions);
    if (snapshot.status.marketOpen === false) {
      const clock = asObj(await client.clock(signal), "clock");
      snapshot.nextOpen = optStr(clock, "nextOpen");
    }
  } catch (error) {
    if (signal.aborted) throw error;
    snapshot.accountError = asApiError(error);
  }
  return snapshot;
}

/** Groups thousands of a decimal string without converting it to a Number. */
export function formatDecimal(value: string | null): string {
  if (value === null) return "No disponible";
  const negative = value.startsWith("-");
  const [int, frac] = (negative ? value.slice(1) : value).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${grouped}${frac !== undefined ? `.${frac}` : ""}`;
}
export function formatUsd(value: string | null): string {
  if (value === null) return "No disponible";
  return value.startsWith("-") ? `−$${formatDecimal(value.slice(1))}` : `$${formatDecimal(value)}`;
}
