"use client";

import { useRef, useState } from "react";

type Point = { text: string; evidenceIds: string[] };
type Section = "supportingReasons" | "counterpoints" | "riskFactors" | "dataGaps" | "limitations";
type Response = {
  analysis: { symbol: string; companyName: string; recommendation: string; confidence: number };
  narrative: {
    generationMode: "llm" | "deterministic";
    model: string | null;
    reason: { message: string } | null;
    facts: { provenance: string; supervisorStatus: string };
    report: { title: string; overview: Point } & Record<Section, Point[]>;
  };
};

const sections: [Section, string][] = [
  ["supportingReasons", "Razones"], ["counterpoints", "Contrapuntos"],
  ["riskFactors", "Riesgos"], ["dataGaps", "Datos faltantes"], ["limitations", "Limitaciones"],
];

export function NarrativePanel() {
  const [symbol, setSymbol] = useState("NVDA");
  const [result, setResult] = useState<Response | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const busy = useRef(false);

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true;
    setLoading(true); setError(""); setResult(null);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 300_000);
    try {
      const base = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";
      const response = await fetch(`${base}/api/report`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: symbol.trim().toUpperCase(), language: "es" }),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message ?? "No se pudo obtener el informe.");
      if (!data.narrative?.report || !data.analysis) throw new Error("Respuesta incompleta del servidor.");
      setResult(data);
    } catch (failure) {
      setError(failure instanceof Error && failure.name === "AbortError"
        ? "Se agotó el tiempo de espera. Comprueba el servidor antes de repetir."
        : failure instanceof TypeError ? "No se pudo conectar con el backend."
        : failure instanceof Error ? failure.message : "No se pudo obtener el informe.");
    } finally {
      clearTimeout(timer); busy.current = false; setLoading(false);
    }
  }

  return <section className="glass-card" style={{ padding: 24, marginBottom: 24 }} aria-label="Informe de inversión">
    <div className="section-title"><div><p className="label">INFORME DE INVERSIÓN</p><h2>Lectura del comité</h2></div></div>
    <p>Solicita un informe sobre el dataset de demostración. El modelo local puede tardar varios minutos.</p>
    <form onSubmit={generate} style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 16 }}>
      <label>Símbolo <input aria-label="Símbolo del informe" value={symbol} onChange={e => setSymbol(e.target.value)} maxLength={12} required disabled={loading} style={{ padding: 8, marginLeft: 8 }} /></label>
      <button className="transfer-button" type="submit" disabled={loading}>{loading ? "Preparando informe…" : "Generar informe"}</button>
    </form>
    <div aria-live="polite">
      {loading && <p role="status">Analizando evidencias y preparando la explicación. Mantén esta página abierta.</p>}
      {error && <p role="alert">{error}</p>}
      {result && <article style={{ marginTop: 20 }}>
        <p>{result.narrative.generationMode === "llm" ? `Generado por modelo local ${result.narrative.model}` : "Informe determinista"}</p>
        {result.narrative.reason && <p>{result.narrative.reason.message}</p>}
        {result.narrative.facts.provenance === "synthetic" && <p><strong>Datos sintéticos de demostración; no son precios reales de mercado.</strong></p>}
        <h3>{result.narrative.report.title}</h3>
        <p>{result.analysis.symbol} · {result.analysis.recommendation} · Confianza: {Math.round(result.analysis.confidence * 100)}% · Supervisor: {result.narrative.facts.supervisorStatus}</p>
        <p>{result.narrative.report.overview.text}</p>
        {sections.map(([key, title]) => <section key={key} style={{ marginTop: 16 }}>
          <h4>{title}</h4>
          {result.narrative.report[key]?.length ? <ul>{result.narrative.report[key].map((point, index) => <li key={index}>{point.text}<small style={{ display: "block", opacity: .7 }}>Evidencia: {point.evidenceIds.join(", ")}</small></li>)}</ul> : <p>Sin elementos reportados.</p>}
        </section>)}
      </article>}
    </div>
  </section>;
}
