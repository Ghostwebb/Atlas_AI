"use client";

import { useEffect, useState } from "react";
import type { PaperClient } from "../controller";
import { availabilityOf, formatDecimal, formatUsd, loadAccount, type AccountSnapshot, type Availability } from "./account";
import { ErrorNotice } from "./ErrorNotice";
import { AVAILABILITY } from "./labels";

/**
 * Feature status, market, account and positions from the backend (Alpaca Paper account).
 * Loaded on mount, on "Actualizar" and when `refreshKey` changes. No automatic polling:
 * /status calls Alpaca's clock on every request.
 */
export function AccountPanel({ client, refreshKey, onAvailability }: {
  client: PaperClient; refreshKey: string; onAvailability: (availability: Availability) => void;
}) {
  const [snapshot, setSnapshot] = useState<AccountSnapshot | null>(null);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const abort = new AbortController();
    loadAccount(client, abort.signal).then(result => {
      setSnapshot(result);
      setLoading(false);
      onAvailability(availabilityOf(result.status, result.statusError));
    }, () => { /* aborted on unmount or refresh */ });
    return () => abort.abort();
  }, [client, reload, refreshKey, onAvailability]);

  const availability = snapshot ? availabilityOf(snapshot.status, snapshot.statusError) : "loading";
  const status = snapshot?.status ?? null;
  const account = snapshot?.account ?? null;
  const market = status?.marketOpen === true ? "Abierto (sesión regular)" : status?.marketOpen === false ? "Cerrado" : "No disponible";

  return <section className="pt-card" aria-labelledby="pt-account-title" aria-busy={loading}>
    <div className="pt-card-head">
      <div><p className="label">CUENTA ALPACA PAPER</p><h2 id="pt-account-title">Estado y saldo</h2></div>
      <button type="button" className="pt-secondary" disabled={loading}
        onClick={() => { setLoading(true); setReload(r => r + 1); }}>{loading ? "Actualizando…" : "Actualizar"}</button>
    </div>
    <p className="pt-source">Datos de la cuenta Alpaca Paper leídos a través del backend de ATLAS. Dinero ficticio.</p>
    <dl className="pt-kv">
      <dt>Paper Trading</dt>
      <dd><span className={`pt-badge pt-avail-${availability}`}>{AVAILABILITY[availability].label}</span></dd>
      <dt>Mercado</dt><dd>{availability === "available" ? market : "No disponible"}</dd>
      {snapshot?.nextOpen && <><dt>Próxima apertura</dt><dd>{new Date(snapshot.nextOpen).toLocaleString()}</dd></>}
    </dl>
    <p className="pt-muted">{AVAILABILITY[availability].detail}</p>
    {snapshot?.statusError && <ErrorNotice error={snapshot.statusError} title="No se pudo leer el estado" />}
    {snapshot?.accountError && <ErrorNotice error={snapshot.accountError} title="No se pudo leer la cuenta" />}

    {availability === "available" && !snapshot?.accountError && <>
      <h3 className="pt-subtitle">Saldo</h3>
      <dl className="pt-kv">
        <dt>Efectivo</dt><dd>{formatUsd(account?.cash ?? null)}</dd>
        <dt>Poder de compra (sin margen)</dt><dd>{formatUsd(account?.nonMarginableBuyingPower ?? null)}</dd>
        <dt>Poder de compra</dt><dd>{formatUsd(account?.buyingPower ?? null)}</dd>
        <dt>Patrimonio</dt><dd>{formatUsd(account?.equity ?? null)}</dd>
        <dt>Estado de la cuenta</dt><dd>{account?.status ?? "No disponible"}
          {(account?.tradingBlocked || account?.accountBlocked) && " · bloqueada para operar"}</dd>
      </dl>
      <h3 className="pt-subtitle">Posiciones</h3>
      {snapshot?.positions === null ? <p className="pt-muted">No disponible</p>
        : snapshot?.positions.length === 0 ? <p className="pt-muted">Sin posiciones abiertas.</p>
        : <ul className="pt-positions">{snapshot?.positions.map(p => <li key={p.symbol}>
            <strong>{p.symbol}</strong>
            <span>{formatDecimal(p.qty)} acc. · disponibles {formatDecimal(p.qtyAvailable)}</span>
            <small>Precio medio {formatUsd(p.avgEntryPrice)} · Valor {formatUsd(p.marketValue)}</small>
          </li>)}</ul>}
    </>}
  </section>;
}
