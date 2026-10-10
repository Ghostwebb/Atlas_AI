/**
 * Operation journal: a minimal, versioned record that lets a controller recover after a reload
 * WITHOUT re-enabling a confirmation (or a cancel) whose outcome is unknown.
 *
 * Record (v1): { v: 1, proposalId, pendingConfirm, pendingCancel }. No amounts, no credentials.
 *   pendingConfirm  a confirm request was (or is about to be) sent and no conclusive answer arrived;
 *   pendingCancel   a cancel request was sent and the order has not been read since.
 *
 * Load policy (conservative):
 *   empty storage            → nothing to recover
 *   valid v1 record          → recover it as written
 *   legacy plain id          → recover with pendingConfirm = true (the old format never recorded intent)
 *   unknown version / missing or malformed flags, but a usable id
 *                            → recover with pendingConfirm = true and pendingCancel = true
 *   corrupt JSON / no usable id → "invalid": nothing can be recovered (the operation is unknown)
 *   storage not accessible   → "unavailable": recovery is impossible and confirm is blocked
 *
 * sessionStorage covers this browser tab and its reloads only. It is not a global guarantee
 * across tabs or devices; the backend keeps its own guarantees (atomic claim, no resubmission).
 */

export interface JournalRecord {
  v: 1;
  proposalId: string;
  pendingConfirm: boolean;
  pendingCancel: boolean;
}

export type JournalLoad =
  | { kind: "empty" }
  | { kind: "record"; record: JournalRecord; note: "ok" | "legacy" | "incomplete" | "unknown_version" }
  | { kind: "invalid" }
  | { kind: "unavailable" };

export interface OperationJournal {
  /** Never throws. */
  load(): JournalLoad;
  /** Synchronous. Returns false if the record could not be stored. Never throws. */
  save(record: JournalRecord): boolean;
  /** Never throws. */
  clear(): void;
}

const ID = /^[A-Za-z0-9_-]{1,64}$/;
export const JOURNAL_KEY = "atlas.paperTrading.operation";
/** Format written by f2a6010 (plain proposal id). */
export const LEGACY_KEY = "atlas.paperTrading.proposalId";

export function parseJournal(raw: string | null, legacy: string | null): JournalLoad {
  if (raw === null) {
    if (legacy !== null && ID.test(legacy)) {
      return { kind: "record", note: "legacy",
        record: { v: 1, proposalId: legacy, pendingConfirm: true, pendingCancel: false } };
    }
    return legacy === null ? { kind: "empty" } : { kind: "invalid" };
  }
  let data: unknown;
  try { data = JSON.parse(raw); } catch { return { kind: "invalid" }; }
  if (data === null || typeof data !== "object" || Array.isArray(data)) return { kind: "invalid" };
  const o = data as Record<string, unknown>;
  if (typeof o.proposalId !== "string" || !ID.test(o.proposalId)) return { kind: "invalid" };
  if (o.v !== 1) {
    return { kind: "record", note: "unknown_version",
      record: { v: 1, proposalId: o.proposalId, pendingConfirm: true, pendingCancel: true } };
  }
  if (typeof o.pendingConfirm !== "boolean" || typeof o.pendingCancel !== "boolean") {
    return { kind: "record", note: "incomplete",
      record: { v: 1, proposalId: o.proposalId, pendingConfirm: true, pendingCancel: true } };
  }
  return { kind: "record", note: "ok",
    record: { v: 1, proposalId: o.proposalId, pendingConfirm: o.pendingConfirm, pendingCancel: o.pendingCancel } };
}

/** Storage-backed journal (sessionStorage by default). Storage access errors never escape. */
export function createStorageJournal(getStorage: () => Storage | null = () => globalThis.sessionStorage ?? null,
  key = JOURNAL_KEY): OperationJournal {
  const storage = (): Storage | null => { try { return getStorage(); } catch { return null; } };
  return {
    load() {
      const s = storage();
      if (!s) return { kind: "unavailable" };
      try { return parseJournal(s.getItem(key), s.getItem(LEGACY_KEY)); } catch { return { kind: "unavailable" }; }
    },
    save(record) {
      const s = storage();
      if (!s) return false;
      try {
        const text = JSON.stringify(record);
        s.setItem(key, text);
        if (s.getItem(key) !== text) return false; // verify the write
        try { s.removeItem(LEGACY_KEY); } catch { /* legacy key cleanup is best-effort */ }
        return true;
      } catch { return false; }
    },
    clear() {
      const s = storage();
      try { s?.removeItem(key); s?.removeItem(LEGACY_KEY); } catch { /* ignore */ }
    },
  };
}
