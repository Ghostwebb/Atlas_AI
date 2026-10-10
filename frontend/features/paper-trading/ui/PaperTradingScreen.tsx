"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { createPaperClient } from "../client";
import { createStorageJournal } from "../journal";
import { PAPER_NOTICE } from "../policy";
import { usePaperTradingController } from "../usePaperTradingController";
import type { Availability } from "./account";
import { AccountPanel } from "./AccountPanel";
import { OperationPanel } from "./OperationPanel";
import { OrderForm } from "./OrderForm";
import "./paper-trading.css";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export function PaperTradingScreen() {
  const [client] = useState(() => createPaperClient(API_BASE_URL));
  // The controller owns recovery: it reads this tab's journal (sessionStorage) when it is created and
  // writes each confirm/cancel intent before sending it. The page never resumes or confirms by itself.
  const [journal] = useState(() => createStorageJournal());
  const { controller, state } = usePaperTradingController({ client, journal });
  const [availability, setAvailability] = useState<Availability>("loading");
  const onAvailability = useCallback((a: Availability) => setAvailability(a), []);
  const proposalId = state?.proposal?.id ?? null;

  // Re-read the account once an operation reaches a final state (fills change balances).
  const refreshKey = state?.phase === "final" && proposalId ? `final:${proposalId}` : "";

  return <div className="pt-canvas">
    <p className="pt-banner" role="note"><strong>{PAPER_NOTICE}</strong> · Cuenta Alpaca Paper, sin dinero real.</p>
    <header className="pt-header">
      <div>
        <p className="breadcrumb">ATLAS AI <span>/</span> PAPER TRADING</p>
        <h1>Paper Trading</h1>
        <p className="subheading">Prepara, revisa y confirma órdenes de prueba en tu cuenta Alpaca Paper.</p>
      </div>
      <Link className="pt-back" href="/">← Volver al dashboard</Link>
    </header>
    <div className="pt-grid">
      <div className="pt-column">
        <OrderForm controller={controller} state={state} availability={availability} />
        <OperationPanel controller={controller} state={state} />
      </div>
      <div className="pt-column">
        <AccountPanel client={client} refreshKey={refreshKey} onAvailability={onAvailability} />
        <section className="pt-card pt-separation" aria-labelledby="pt-sep-title">
          <p className="label">SEPARACIÓN DE DATOS</p>
          <h2 id="pt-sep-title">Análisis sintético ≠ cuenta paper</h2>
          <ul>
            <li><strong>Análisis de ATLAS:</strong> usa un dataset sintético de demostración. No es mercado real y no se usa
              aquí para estimar acciones, importes ni valoración de órdenes.</li>
            <li><strong>Cuenta Alpaca Paper:</strong> saldo, posiciones y órdenes llegan del backend. No hay cotización de
              referencia en este contrato.</li>
            <li><strong>Fixtures:</strong> solo existen en las pruebas automáticas; esta pantalla nunca muestra datos simulados
              como si fueran de Alpaca.</li>
          </ul>
        </section>
      </div>
    </div>
  </div>;
}
