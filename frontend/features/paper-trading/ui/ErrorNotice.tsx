import type { ControllerError } from "../controller";
import { errorMessage } from "./labels";

/** Readable message plus accessible technical detail (code, message, correlationId). */
export function ErrorNotice({ error, side, title }: {
  error: Pick<ControllerError, "code" | "message" | "correlationId"> & Partial<ControllerError>;
  side?: "buy" | "sell" | null;
  title?: string;
}) {
  const full: ControllerError = { status: 0, proposalId: null, ...error };
  return <div className="pt-error" role="alert">
    {title && <strong>{title}</strong>}
    <p>{errorMessage(full, side ?? null)}</p>
    <details>
      <summary>Detalle técnico</summary>
      <dl className="pt-kv">
        <dt>code</dt><dd><code>{full.code}</code></dd>
        <dt>message</dt><dd>{full.message}</dd>
        {full.correlationId && <><dt>correlationId</dt><dd><code>{full.correlationId}</code></dd></>}
      </dl>
    </details>
  </div>;
}
