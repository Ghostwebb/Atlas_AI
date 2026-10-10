"use client";

import { useId, useState, type FormEvent } from "react";
import type { ControllerState, PaperTradingController } from "../controller";
import type { Availability } from "./account";

/**
 * Prepare form. It only calls controller.prepare(); it never confirms.
 * Amounts stay exactly as typed (decimal strings); the controller validates them.
 */
export function OrderForm({ controller, state, availability }: {
  controller: PaperTradingController | null; state: ControllerState | null; availability: Availability;
}) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [symbol, setSymbol] = useState("");
  const [amount, setAmount] = useState("");
  const ids = useId();
  const preparing = state?.busy === "prepare";
  const enabled = Boolean(controller && state?.canPrepare) && availability === "available";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!controller || !enabled) return;
    const value = amount.trim();
    await controller.prepare(side === "buy"
      ? { symbol, side: "buy", notional: value }
      : { symbol, side: "sell", qty: value });
  }

  return <section className="pt-card" aria-labelledby={`${ids}-title`}>
    <p className="label">NUEVA OPERACIÓN</p>
    <h2 id={`${ids}-title`}>Preparar una propuesta</h2>
    <p className="pt-muted">Preparar no envía ninguna orden ni reserva fondos o acciones. Tú decides el lado y el importe;
      el análisis de ATLAS no genera propuestas.</p>
    <form className="pt-form" onSubmit={submit} aria-busy={preparing}>
      <fieldset className="pt-sides" disabled={preparing}>
        <legend>Tipo de operación</legend>
        <label><input type="radio" name={`${ids}-side`} value="buy" checked={side === "buy"} onChange={() => setSide("buy")} />
          Comprar por importe (USD)</label>
        <label><input type="radio" name={`${ids}-side`} value="sell" checked={side === "sell"} onChange={() => setSide("sell")} />
          Reducir una posición (acciones)</label>
      </fieldset>
      <div className="pt-field">
        <label htmlFor={`${ids}-symbol`}>Símbolo</label>
        <input id={`${ids}-symbol`} value={symbol} onChange={e => setSymbol(e.target.value)} maxLength={12}
          autoComplete="off" spellCheck={false} required disabled={preparing} placeholder="NVDA" />
      </div>
      <div className="pt-field">
        <label htmlFor={`${ids}-amount`}>{side === "buy" ? "Importe en USD" : "Número de acciones"}</label>
        <input id={`${ids}-amount`} value={amount} onChange={e => setAmount(e.target.value)} inputMode="decimal"
          maxLength={20} autoComplete="off" required disabled={preparing} aria-describedby={`${ids}-hint`}
          placeholder={side === "buy" ? "100.00" : "0.5"} />
        <small id={`${ids}-hint`}>{side === "buy"
          ? "Hasta 2 decimales, mínimo 1.00 y dentro del límite por orden del servidor."
          : "Hasta 9 decimales. No puede superar las acciones disponibles de la posición."}</small>
      </div>
      <button type="submit" className="pt-primary" disabled={!enabled || preparing}>
        {preparing ? "Preparando…" : "Preparar propuesta"}</button>
      {availability !== "available" && availability !== "loading" &&
        <p className="pt-muted">Paper Trading no está disponible ahora; revisa el estado de la cuenta.</p>}
      {state && !state.canPrepare && !preparing && state.phase !== "idle" &&
        <p className="pt-muted">Termina o sigue la operación actual antes de preparar otra.</p>}
    </form>
  </section>;
}
