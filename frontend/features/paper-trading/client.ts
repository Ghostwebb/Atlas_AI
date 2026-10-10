import type { Account, BrokerOrder, Clock, PaperStatus, Position, Proposal, ProposalRequest } from "./types";

export class PaperApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly correlationId: string | null;
  readonly proposalId: string | null;
  constructor(message: string, code: string, status = 0, correlationId: string | null = null, proposalId: string | null = null) {
    super(message); this.name = "PaperApiError";
    this.code = code; this.status = status; this.correlationId = correlationId; this.proposalId = proposalId;
  }
}

/** No retries, credentials or broker URL. Supply fixture fetch in tests. */
export function createPaperClient(baseUrl: string, transport: typeof fetch = fetch) {
  const base = `${baseUrl.replace(/\/$/, "")}/api/paper`;
  async function request<T>(path: string, method = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
    let response: Response;
    try {
      response = await transport(`${base}${path}`, {
        method, signal, cache: "no-store", credentials: "omit",
        ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new PaperApiError("No se pudo obtener una respuesta. Si estabas confirmando, consulta la propuesta; no reenvíes la orden.", "NETWORK_ERROR");
    }
    const data: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const error = data !== null && typeof data === "object" ? data as Record<string, unknown> : {};
      throw new PaperApiError(
        typeof error.message === "string" ? error.message : "El backend devolvió un error.",
        typeof error.code === "string" ? error.code : "HTTP_ERROR", response.status,
        typeof error.correlationId === "string" ? error.correlationId : response.headers.get("X-Correlation-Id"),
        typeof error.proposalId === "string" ? error.proposalId : null,
      );
    }
    if (data === null) throw new PaperApiError("Respuesta JSON inválida. Consulta el estado antes de repetir una confirmación.", "INVALID_RESPONSE", response.status);
    return data as T;
  }
  const id = encodeURIComponent;
  return {
    status: (signal?: AbortSignal) => request<PaperStatus>("/status", "GET", undefined, signal),
    account: (signal?: AbortSignal) => request<Account>("/account", "GET", undefined, signal),
    positions: (signal?: AbortSignal) => request<Position[]>("/positions", "GET", undefined, signal),
    clock: (signal?: AbortSignal) => request<Clock>("/clock", "GET", undefined, signal),
    prepare: (body: ProposalRequest, signal?: AbortSignal) => request<Proposal>("/proposals", "POST", body, signal),
    proposal: (proposalId: string, signal?: AbortSignal) => request<Proposal>(`/proposals/${id(proposalId)}`, "GET", undefined, signal),
    confirm: (proposalId: string, signal?: AbortSignal) => request<Proposal>(`/proposals/${id(proposalId)}/confirm`, "POST", { confirmation: "CONFIRM_PAPER_ORDER" }, signal),
    reconcile: (proposalId: string, signal?: AbortSignal) => request<Proposal>(`/proposals/${id(proposalId)}/reconcile`, "POST", undefined, signal),
    order: (orderId: string, signal?: AbortSignal) => request<BrokerOrder>(`/orders/${id(orderId)}`, "GET", undefined, signal),
    cancel: (orderId: string, signal?: AbortSignal) => request<{ cancelRequested: true; order: BrokerOrder }>(`/orders/${id(orderId)}/cancel`, "POST", { confirmation: "CANCEL_PAPER_ORDER" }, signal),
    orders: (status: "open" | "closed" | "all" = "all", signal?: AbortSignal) => request<BrokerOrder[]>(`/orders?status=${status}&limit=50`, "GET", undefined, signal),
  };
}
