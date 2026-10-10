/**
 * Paper Trading operation controller (Phase 6). Framework-free and visual-free.
 *
 * One controller follows ONE operation: prepare → review → (human) confirm → track → (human) cancel.
 * Transport, clock and scheduler are injected, so every path is testable without network or timers.
 * See README.md for states, transitions and invariants.
 */
import { PaperApiError, type createPaperClient } from "./client";
import { PAPER_NOTICE, canCancel as policyCanCancel, canConfirm as policyCanConfirm, isFinalOrder, nextStatusRead } from "./policy";
import type { BrokerOrder, Proposal } from "./types";
import { parseCancel, parseOrder, parseProposal, proposalRequest } from "./validate";

export type PaperClient = ReturnType<typeof createPaperClient>;

export interface Scheduler {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface ControllerOptions {
  client: PaperClient;
  /** "fixture" for tests/demos with HTTP fixtures. A fixture is never a broker connection. */
  source?: "backend" | "fixture";
  now?: () => number;
  scheduler?: Scheduler;
  /** Normal follow-up interval (2000–5000 ms). Default 3000. */
  pollIntervalMs?: number;
  /** Backoff cap. Default 30000. */
  maxBackoffMs?: number;
}

export type Phase =
  | "idle" | "preparing" | "review" | "confirming" | "uncertain" | "tracking" | "final" | "expired";

export interface ControllerError {
  code: string; message: string; status: number; correlationId: string | null; proposalId: string | null;
}

export interface ControllerState {
  readonly notice: typeof PAPER_NOTICE;
  readonly source: "backend" | "fixture";
  readonly phase: Phase;
  /** Last validated backend proposal (its own status / submissionStatus / brokerStatus / reservation). */
  readonly proposal: Proposal | null;
  /** Last validated broker order read through GET /orders/{id} or a cancel response. */
  readonly order: BrokerOrder | null;
  /** Mutation currently in flight (locks every other mutation). */
  readonly busy: "prepare" | "confirm" | "cancel" | null;
  /** A follow-up read is in flight. */
  readonly reading: boolean;
  /** The confirm response was lost, aborted, invalid or contradictory: the order MAY exist. */
  readonly confirmUncertain: boolean;
  /** The cancel response was lost: read the order before allowing another cancel. */
  readonly cancelUncertain: boolean;
  /** A definite confirm error was received; the proposal is re-read before confirm is offered again. */
  readonly verifying: boolean;
  readonly lastError: ControllerError | null;
  /** Delay in ms of the scheduled follow-up read, or null when none is scheduled. */
  readonly nextReadInMs: number | null;
  readonly canPrepare: boolean;
  readonly canConfirm: boolean;
  readonly canCancel: boolean;
  readonly canCheckStatus: boolean;
}

export type ActionResult = { ok: true } | { ok: false; reason: "busy" | "not_allowed" | "disposed" | "error" };

// Error codes the backend defines. A response with one of them is a definite answer from ATLAS.
const BACKEND_CODES = new Set([
  "INVALID_REQUEST", "INVALID_CONFIRMATION", "ORIGIN_NOT_ALLOWED", "PROPOSAL_NOT_FOUND", "ORDER_NOT_FOUND",
  "MARKET_CLOSED", "PROPOSAL_EXPIRED", "SUBMISSION_IN_PROGRESS", "SUBMISSION_UNCERTAIN", "ORDER_NOT_CANCELABLE",
  "RESOURCE_RESERVED", "RECONCILIATION_REQUIRED", "ACCOUNT_NOT_TRADABLE", "ASSET_NOT_SUPPORTED",
  "FRACTIONAL_NOT_SUPPORTED", "ORDER_LIMIT_EXCEEDED", "INSUFFICIENT_BUYING_POWER", "INSUFFICIENT_POSITION",
  "BROKER_REJECTED", "PAPER_DISABLED", "PAPER_NOT_CONFIGURED", "BROKER_UNAVAILABLE",
]);

const realScheduler: Scheduler = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: handle => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

function toError(error: unknown): ControllerError {
  if (error instanceof PaperApiError) {
    return { code: error.code, message: error.message, status: error.status,
      correlationId: error.correlationId, proposalId: error.proposalId };
  }
  const aborted = error instanceof Error && error.name === "AbortError";
  return { code: aborted ? "ABORTED" : "UNEXPECTED_ERROR",
    message: aborted ? "La petición se canceló." : "Error inesperado.", status: 0, correlationId: null, proposalId: null };
}

/** True only when ATLAS itself answered with a documented code (not network, abort or malformed data). */
const isDefinite = (e: ControllerError) => e.status > 0 && BACKEND_CODES.has(e.code);

export function createPaperTradingController(options: ControllerOptions) {
  const { client } = options;
  const source = options.source ?? "backend";
  const now = options.now ?? (() => Date.now());
  const scheduler = options.scheduler ?? realScheduler;
  const interval = Math.min(5000, Math.max(2000, options.pollIntervalMs ?? 3000));
  const maxBackoff = Math.max(interval, options.maxBackoffMs ?? 30000);

  // --- internal state (single source of truth) ---
  let session = 0; // bumped when the operation changes; late responses of older sessions are ignored
  let disposed = false;
  let proposal: Proposal | null = null;
  let order: BrokerOrder | null = null;
  let busy: ControllerState["busy"] = null;
  let confirmUncertain = false;
  let cancelUncertain = false;
  let verifying = false;
  let lastError: ControllerError | null = null;
  let failures = 0;
  let readPromise: Promise<void> | null = null;
  let timer: unknown = null;
  let timerDelay: number | null = null;
  let expiryTimer: unknown = null;
  const controllers = new Set<AbortController>();
  const listeners = new Set<() => void>();
  let snapshot: ControllerState;

  function phase(): Phase {
    if (busy === "prepare" && proposal === null) return "preparing";
    if (proposal === null) return "idle";
    if (busy === "confirm") return "confirming";
    if (confirmUncertain) return "uncertain";
    const p = proposal;
    if (p.status === "expired") return "expired";
    if (p.submissionStatus === "rejected_by_broker") return "final";
    if (p.submissionStatus === "submitting" || p.submissionStatus === "submission_unknown") return "uncertain";
    if (p.submissionStatus === "submitted") return isFinalOrder(p.brokerStatus) ? "final" : "tracking";
    // open + not_submitted / failed_before_submit: only an unsent proposal can expire locally.
    return now() >= Date.parse(p.expiresAt) ? "expired" : "review";
  }

  function build(): ControllerState {
    const ph = phase();
    const idleMutations = busy === null && !disposed;
    return Object.freeze({
      notice: PAPER_NOTICE, source, phase: ph, proposal, order, busy,
      reading: readPromise !== null, confirmUncertain, cancelUncertain, verifying, lastError,
      nextReadInMs: timerDelay,
      canPrepare: idleMutations && ["idle", "review", "expired", "final"].includes(ph),
      canConfirm: idleMutations && ph === "review" && !verifying && proposal !== null && policyCanConfirm(proposal, now()),
      canCancel: idleMutations && ph === "tracking" && !cancelUncertain && proposal !== null && policyCanCancel(proposal),
      canCheckStatus: !disposed && (ph === "uncertain" || ph === "tracking" || verifying || cancelUncertain),
    });
  }

  function emit() {
    if (disposed) return;
    snapshot = build();
    for (const listener of [...listeners]) listener();
  }
  snapshot = build();

  function abortable() {
    const controller = new AbortController();
    controllers.add(controller);
    return { signal: controller.signal, done: () => controllers.delete(controller) };
  }

  function clearTimer() {
    if (timer !== null) scheduler.clearTimeout(timer);
    timer = null;
    timerDelay = null;
  }

  function scheduleExpiryNotice() {
    if (expiryTimer !== null) scheduler.clearTimeout(expiryTimer);
    expiryTimer = null;
    if (proposal === null || phase() !== "review") return;
    const ms = Date.parse(proposal.expiresAt) - now();
    if (ms > 0) expiryTimer = scheduler.setTimeout(() => { expiryTimer = null; emit(); }, ms);
  }

  /** Is there anything to follow at the backend for the current operation? */
  function needsFollowUp(): boolean {
    if (proposal === null || disposed) return false;
    if (confirmUncertain || verifying || cancelUncertain) return true;
    return nextStatusRead(proposal) !== null;
  }

  function scheduleNext() {
    clearTimer();
    if (!needsFollowUp()) return;
    const delay = Math.min(maxBackoff, interval * 2 ** failures);
    const mySession = session;
    timerDelay = delay;
    timer = scheduler.setTimeout(() => {
      timer = null;
      timerDelay = null;
      if (mySession === session && !disposed) void follow();
    }, delay);
  }

  function acceptProposal(p: Proposal, expectedId: string) {
    if (p.id !== expectedId) throw new PaperApiError("La respuesta pertenece a otra propuesta.", "INVALID_RESPONSE");
    proposal = p;
  }

  /** One follow-up read. Never confirms, never cancels, never resends. */
  async function readOnce(mySession: number, signal: AbortSignal) {
    const p = proposal as Proposal;
    const stale = () => mySession !== session || disposed;
    if (confirmUncertain || verifying) {
      // First learn what ATLAS stored; reconcile on the next read if it says so.
      const local = parseProposal(await client.proposal(p.id, signal));
      if (stale()) return;
      acceptProposal(local, p.id);
      if (verifying) verifying = false;
      if (confirmUncertain) {
        // Only explicit backend states end the local uncertainty. "open + not_submitted" does not:
        // the lost request may still be processed.
        const proof = local.status === "expired" || local.submissionStatus !== "not_submitted";
        if (proof) confirmUncertain = false;
      }
      return;
    }
    const next = nextStatusRead(p);
    if (next === null && !cancelUncertain) return;
    if (next?.kind === "reconcile") {
      const reconciled = parseProposal(await client.reconcile(p.id, signal));
      if (stale()) return;
      acceptProposal(reconciled, p.id);
      return;
    }
    const orderId = next?.id ?? p.brokerOrderId;
    if (!orderId) return;
    const o = parseOrder(await client.order(orderId, signal));
    if (stale()) return;
    if (o.id !== orderId || (o.proposalId !== null && o.proposalId !== p.id)) {
      throw new PaperApiError("La orden recibida no corresponde a esta operación.", "INVALID_RESPONSE");
    }
    // GET /orders updated ATLAS's records; read them back (SQLite only).
    const refreshed = parseProposal(await client.proposal(p.id, signal));
    if (stale()) return;
    acceptProposal(refreshed, p.id);
    order = o;
    cancelUncertain = false;
  }

  /** Runs one read; concurrent callers share it (one read in flight per operation). */
  function follow(): Promise<void> {
    if (readPromise !== null) return readPromise;
    if (!needsFollowUp()) return Promise.resolve();
    clearTimer();
    const mySession = session;
    const { signal, done } = abortable();
    const run = (async () => {
      try {
        await readOnce(mySession, signal);
        if (mySession !== session || disposed) return;
        // A read that leaves the confirmation uncertain also backs off.
        failures = confirmUncertain ? Math.min(failures + 1, 10) : 0;
        lastError = null;
      } catch (error) {
        if (mySession !== session || disposed) return;
        failures = Math.min(failures + 1, 10);
        lastError = toError(error);
      } finally {
        done();
        if (mySession === session && !disposed) {
          readPromise = null;
          scheduleNext();
          scheduleExpiryNotice();
          emit();
        }
      }
    })();
    readPromise = run;
    emit();
    return run;
  }

  function startOperation() {
    session += 1;
    clearTimer();
    readPromise = null;
    for (const c of controllers) c.abort();
    controllers.clear();
    proposal = null; order = null;
    confirmUncertain = false; cancelUncertain = false; verifying = false;
    lastError = null; failures = 0;
  }

  // --- public API ---------------------------------------------------------------

  /** Prepares a proposal. Never confirms or sends an order. */
  async function prepare(input: unknown): Promise<ActionResult> {
    if (disposed) return { ok: false, reason: "disposed" };
    if (busy !== null) return { ok: false, reason: "busy" };
    if (!snapshot.canPrepare) return { ok: false, reason: "not_allowed" };
    let body;
    try {
      body = proposalRequest(input);
    } catch (error) {
      lastError = { ...toError(error), code: "INVALID_INPUT", message: "Datos de la propuesta no válidos." };
      emit();
      return { ok: false, reason: "error" };
    }
    startOperation();
    busy = "prepare"; // synchronous lock, before any await
    const mySession = session;
    emit();
    const { signal, done } = abortable();
    try {
      const p = parseProposal(await client.prepare(body, signal));
      if (mySession !== session || disposed) return { ok: false, reason: "disposed" };
      if (p.status !== "open" || p.submissionStatus !== "not_submitted") {
        throw new PaperApiError("El backend devolvió una propuesta preparada no válida.", "INVALID_RESPONSE");
      }
      proposal = p;
      return { ok: true };
    } catch (error) {
      if (mySession !== session || disposed) return { ok: false, reason: "disposed" };
      lastError = toError(error);
      return { ok: false, reason: "error" };
    } finally {
      done();
      if (mySession === session && !disposed) {
        busy = null;
        scheduleExpiryNotice();
        emit();
      }
    }
  }

  /** Confirms the current proposal. Must only be called from an explicit human action. Never retried. */
  async function confirm(): Promise<ActionResult> {
    if (disposed) return { ok: false, reason: "disposed" };
    if (busy !== null) return { ok: false, reason: "busy" };
    if (!snapshot.canConfirm || proposal === null || !policyCanConfirm(proposal, now())) {
      return { ok: false, reason: "not_allowed" };
    }
    busy = "confirm"; // synchronous lock: a second call before any render sees it
    const id = proposal.id;
    const mySession = session;
    clearTimer();
    emit();
    const { signal, done } = abortable();
    let result: ActionResult = { ok: true };
    try {
      const p = parseProposal(await client.confirm(id, signal));
      if (mySession !== session || disposed) return { ok: false, reason: "disposed" };
      acceptProposal(p, id);
      if (p.status !== "confirmed") throw new PaperApiError("Confirmación contradictoria.", "INVALID_RESPONSE");
      lastError = null;
    } catch (error) {
      if (mySession !== session || disposed) return { ok: false, reason: "disposed" };
      lastError = toError(error);
      // Definite answer from ATLAS: re-read before offering confirm again.
      // Anything else (network, abort, malformed, unknown code): the order MAY exist.
      if (isDefinite(lastError)) verifying = true;
      else confirmUncertain = true;
      result = { ok: false, reason: "error" };
    } finally {
      done();
      if (mySession === session && !disposed) {
        busy = null;
        failures = 0;
        if (verifying || confirmUncertain) void follow(); // a READ; never another confirm
        else scheduleNext();
        emit();
      }
    }
    return result;
  }

  /** Requests cancellation. Must only be called from an explicit human action. */
  async function cancel(): Promise<ActionResult> {
    if (disposed) return { ok: false, reason: "disposed" };
    if (busy !== null) return { ok: false, reason: "busy" };
    if (!snapshot.canCancel || proposal === null || !proposal.brokerOrderId) return { ok: false, reason: "not_allowed" };
    busy = "cancel"; // synchronous lock
    const orderId = proposal.brokerOrderId;
    const mySession = session;
    emit();
    const { signal, done } = abortable();
    let result: ActionResult = { ok: true };
    try {
      const response = parseCancel(await client.cancel(orderId, signal));
      if (mySession !== session || disposed) return { ok: false, reason: "disposed" };
      if (response.order.id !== orderId) throw new PaperApiError("Cancelación contradictoria.", "INVALID_RESPONSE");
      order = response.order; // e.g. pending_cancel (not final) or filled (lost the race)
      lastError = null;
    } catch (error) {
      if (mySession !== session || disposed) return { ok: false, reason: "disposed" };
      lastError = toError(error);
      result = { ok: false, reason: "error" };
    } finally {
      done();
      if (mySession === session && !disposed) {
        busy = null;
        // Whatever happened, read the order before allowing another cancel.
        cancelUncertain = true;
        failures = 0;
        emit();
        void follow();
      }
    }
    return result;
  }

  /** Manual "Consultar estado". Joins an in-flight read or runs the scheduled one now. Read-only. */
  function checkStatus(): Promise<void> {
    if (disposed) return Promise.resolve();
    return follow();
  }

  /** Resumes following an existing proposal (for example after a reload). Read-only: never confirms. */
  async function resume(proposalId: string): Promise<ActionResult> {
    if (disposed) return { ok: false, reason: "disposed" };
    if (busy !== null) return { ok: false, reason: "busy" };
    startOperation();
    const mySession = session;
    const { signal, done } = abortable();
    try {
      const p = parseProposal(await client.proposal(proposalId, signal));
      if (mySession !== session || disposed) return { ok: false, reason: "disposed" };
      acceptProposal(p, proposalId);
      return { ok: true };
    } catch (error) {
      if (mySession !== session || disposed) return { ok: false, reason: "disposed" };
      lastError = toError(error);
      return { ok: false, reason: "error" };
    } finally {
      done();
      if (mySession === session && !disposed) {
        scheduleNext();
        scheduleExpiryNotice();
        emit();
      }
    }
  }

  /** Stops everything: aborts requests, clears timers, ignores late responses. */
  function dispose() {
    if (disposed) return;
    disposed = true;
    session += 1;
    clearTimer();
    if (expiryTimer !== null) scheduler.clearTimeout(expiryTimer);
    expiryTimer = null;
    for (const c of controllers) c.abort();
    controllers.clear();
    listeners.clear();
  }

  return {
    getState: (): ControllerState => snapshot,
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    prepare, confirm, cancel, checkStatus, resume, dispose,
  };
}

export type PaperTradingController = ReturnType<typeof createPaperTradingController>;
