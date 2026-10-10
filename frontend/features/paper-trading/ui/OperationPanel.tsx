"use client";

import { useEffect, useRef, useState } from "react";
import type { ControllerState, PaperTradingController } from "../controller";
import { formatDecimal, formatUsd } from "./account";
import { ErrorNotice } from "./ErrorNotice";
import { BROKER_LABEL, PHASE_LABEL, PROPOSAL_STATUS_LABEL, RESERVATION_LABEL, SUBMISSION_LABEL } from "./labels";

/** Display-only countdown. The controller decides expiry; this never triggers actions. */
function Countdown({ expiresAt, active }: { expiresAt: string; active: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  const ms = Date.parse(expiresAt) - now;
  const time = new Date(expiresAt).toLocaleTimeString();
  if (!active || ms <= 0) return <>{time}</>;
  const s = Math.floor(ms / 1000);
  return <>{time} <span className="pt-muted">(quedan {Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")})</span></>;
}

/** Error of the last action (kept after verification reads) and, if different, of the last read. */
function Errors({ state, side }: { state: ControllerState; side: "buy" | "sell" | null }) {
  return <>
    {state.actionError && <ErrorNotice error={state.actionError} side={side} title="La última acción no se completó" />}
    {state.lastError && state.lastError !== state.actionError && <ErrorNotice error={state.lastError} side={side} title="Última consulta" />}
  </>;
}

const REVIEW_PHASES = new Set(["review", "confirming", "expired"]);

export function OperationPanel({ controller, state }: { controller: PaperTradingController | null; state: ControllerState | null }) {
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const statusHeading = useRef<HTMLHeadingElement>(null);
  const lastPhase = useRef<string | null>(null);
  const phase = state?.phase ?? null;

  // Move focus only when the phase changes (never on polling ticks).
  useEffect(() => {
    const previous = lastPhase.current;
    lastPhase.current = phase;
    if (previous === null || previous === phase) return;
    if (phase === "review") reviewHeading.current?.focus();
    else if (phase === "uncertain" || phase === "tracking" || phase === "final" || (phase === "expired" && previous === "confirming")) {
      statusHeading.current?.focus();
    }
  }, [phase]);

  if (!state || !controller) return <section className="pt-card" aria-busy="true"><p className="pt-muted">Cargando…</p></section>;
  const p = state.proposal;
  const side = p?.side ?? null;
  const live = <p className="pt-visually-hidden" aria-live="polite">{PHASE_LABEL[state.phase]}</p>;

  if (!p) {
    return <section className="pt-card" aria-labelledby="pt-op-title">
      {live}
      <p className="label">OPERACIÓN</p>
      <h2 id="pt-op-title">Sin operación activa</h2>
      <p className="pt-muted">Prepara una propuesta para revisarla aquí antes de confirmar.</p>
      <Errors state={state} side={side} />
    </section>;
  }

  const sent = p.status === "confirmed" || state.confirmUncertain;
  const showReview = !sent && REVIEW_PHASES.has(state.phase);
  const order = state.order;
  const brokerStatus = p.brokerStatus;
  const filledQty = order?.filledQty ?? p.filledQty;
  const avgPrice = order?.filledAvgPrice ?? p.filledAvgPrice;
  const uncertain = state.phase === "uncertain" || state.cancelUncertain || state.suspect;
  const cancelNote = brokerStatus === "pending_cancel" ? "Cancelación pendiente: Alpaca aún no la ha confirmado."
    : brokerStatus === "unrecognized" || brokerStatus === null ? "Estado del broker desconocido: puedes consultar, pero no cancelar."
    : state.cancelUncertain ? "Consultando la orden antes de permitir otra cancelación."
    : null;

  return <section className="pt-card" aria-labelledby={showReview ? "pt-review-title" : "pt-status-title"}>
    {live}
    {showReview && <>
      <p className="label">REVISIÓN</p>
      <h2 id="pt-review-title" ref={reviewHeading} tabIndex={-1}>Revisa la propuesta antes de confirmar</h2>
      <dl className="pt-kv">
        <dt>Símbolo</dt><dd><strong>{p.symbol}</strong></dd>
        <dt>Lado</dt><dd>{p.side === "buy" ? "Compra por importe" : "Venta por cantidad"}</dd>
        {p.side === "buy" ? <><dt>Importe</dt><dd>{formatUsd(p.notional)}</dd></>
          : <><dt>Cantidad</dt><dd>{formatDecimal(p.qty)} acciones</dd></>}
        <dt>Orden</dt><dd>Mercado · válida hoy (sesión regular)</dd>
        <dt>Vence</dt><dd><Countdown expiresAt={p.expiresAt} active={state.phase === "review"} /></dd>
      </dl>
      <p className="pt-notice-inline">Preparar no ha enviado la orden ni reservado recursos. Al confirmar, ATLAS vuelve a
        validar la cuenta y Alpaca Paper aún puede rechazarla. El precio de ejecución no se conoce de antemano.</p>
      <h3 className="pt-subtitle">Verificaciones</h3>
      <ul className="pt-checks">{p.checks.map(c => <li key={c.name} className={c.passed ? "ok" : "fail"}>
        <span aria-hidden="true">{c.passed ? "✓" : "✗"}</span>
        <span><strong>{c.name}</strong> — {c.detail}<span className="pt-visually-hidden">{c.passed ? " (correcta)" : " (fallida)"}</span></span>
      </li>)}</ul>
      <h3 className="pt-subtitle">Advertencias</h3>
      <ul className="pt-warnings">{p.warnings.map(w => <li key={w}>{w}</li>)}</ul>
      {state.phase === "expired" && <p className="pt-error" role="alert">La propuesta venció sin enviarse. Prepara una nueva.</p>}
      <Errors state={state} side={side} />
      <div className="pt-actions">
        <button type="button" className="pt-primary" disabled={!state.canConfirm}
          onClick={() => { void controller.confirm(); }}>
          {state.busy === "confirm" ? "Confirmando…" : "Confirmar orden paper"}</button>
        {state.verifying && <span className="pt-muted" role="status">Comprobando el estado antes de permitir otra confirmación…</span>}
      </div>
    </>}

    {!showReview && <>
      <p className="label">OPERACIÓN {p.symbol} · {p.side === "buy" ? `COMPRA ${formatUsd(p.notional)}` : `VENTA ${formatDecimal(p.qty)} ACC.`}</p>
      <h2 id="pt-status-title" ref={statusHeading} tabIndex={-1}>{PHASE_LABEL[state.phase]}</h2>
      {uncertain && <div className="pt-uncertain">
        <p><strong>Resultado incierto.</strong> {state.confirmUncertain
          ? "Se perdió la respuesta de la confirmación: la orden puede existir. No se reenviará."
          : state.suspect ? "La última respuesta no era coherente con esta operación; las acciones quedan bloqueadas."
          : state.cancelUncertain ? "No se confirmó el resultado de la cancelación."
          : "El backend aún no sabe si la orden llegó a Alpaca. No se reenviará."}
          {" "}Usa «Consultar estado».</p>
      </div>}
      <dl className="pt-kv pt-states">
        <dt>Propuesta</dt><dd>{state.confirmUncertain && p.status === "open"
          ? "Confirmación enviada sin respuesta (la última lectura aún dice «abierta»)" : PROPOSAL_STATUS_LABEL[p.status]}</dd>
        <dt>Envío</dt><dd>{state.confirmUncertain && p.status === "open" ? "Respuesta perdida: resultado incierto" : SUBMISSION_LABEL[p.submissionStatus]}</dd>
        <dt>Broker</dt><dd>{brokerStatus ? BROKER_LABEL[brokerStatus] : "Sin dato"}
          {brokerStatus === "unrecognized" && order?.brokerStatusRaw ? <span className="pt-muted"> ({order.brokerStatusRaw})</span> : null}</dd>
        <dt>Ejecutado</dt><dd>{filledQty === null ? "No disponible" : `${formatDecimal(filledQty)} acciones`}
          {avgPrice !== null && <span className="pt-muted"> · precio medio {formatUsd(avgPrice)}</span>}</dd>
        {p.reservation && <>
          <dt>Reserva</dt><dd>{RESERVATION_LABEL[p.reservation.state]} · {p.reservation.resourceType === "cash"
            ? `${formatUsd(p.reservation.amount)} (consumido ${formatUsd(p.reservation.consumed)})`
            : `${formatDecimal(p.reservation.amount)} acc. (consumido ${formatDecimal(p.reservation.consumed)})`}
            {p.reservation.releaseReason && <span className="pt-muted"> · {p.reservation.releaseReason}</span>}</dd>
        </>}
        {p.brokerOrderId && <><dt>Orden</dt><dd><code>{p.brokerOrderId}</code></dd></>}
      </dl>
      <Errors state={state} side={side} />
      <div className="pt-actions">
        <button type="button" className="pt-secondary" disabled={!state.canCheckStatus || state.reading}
          onClick={() => { void controller.checkStatus(); }}>{state.reading ? "Consultando…" : "Consultar estado"}</button>
        {state.phase === "tracking" && <button type="button" className="pt-danger" disabled={!state.canCancel}
          onClick={() => { void controller.cancel(); }}>{state.busy === "cancel" ? "Cancelando…" : "Cancelar orden"}</button>}
      </div>
      {cancelNote && state.phase === "tracking" && <p className="pt-muted">{cancelNote}</p>}
      <p className="pt-muted pt-poll">{state.reading ? "Actualizando…"
        : state.nextReadInMs !== null ? `Próxima consulta automática en ${Math.round(state.nextReadInMs / 1000)} s.`
        : state.phase === "final" ? "Seguimiento detenido: estado final." : ""}</p>
    </>}
  </section>;
}
