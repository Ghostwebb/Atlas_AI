"use client";

import { useEffect, useRef, useState } from "react";
import type { AgentStyle, InvestmentAgent, Risk } from "./agents-data";
import s from "./agents.module.css";

const styles: { id: AgentStyle; label: string; color: string }[] = [
  { id: "value", label: "Valor", color: "#7863cd" },
  { id: "growth", label: "Crecimiento", color: "#337d78" },
  { id: "momentum", label: "Momentum", color: "#a56c32" },
  { id: "defensive", label: "Preservación de capital", color: "#566b9e" },
];

export default function AgentEditor({ agent, onSave, onDismiss }: {
  agent?: InvestmentAgent;
  onSave: (agent: InvestmentAgent) => void;
  onDismiss: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(agent?.name ?? "");
  const [style, setStyle] = useState<AgentStyle>(agent?.style ?? "value");
  const [risk, setRisk] = useState<Risk>(agent?.risk ?? "Moderado");
  const [description, setDescription] = useState(agent?.description ?? "");
  const [looksFor, setLooksFor] = useState(agent?.looksFor ?? "");
  const [avoids, setAvoids] = useState(agent?.avoids ?? "");
  useEffect(() => { dialog.current?.showModal(); }, []);

  return <dialog ref={dialog} className={s.dialog} onClose={onDismiss} aria-labelledby="editor-title">
    <div className={s.sectionHeading}>
      <div><p className={s.overline}>IDENTIDAD Y ESTRATEGIA</p><h2 id="editor-title">{agent ? `Configurar ${agent.name}` : "Un nuevo punto de vista"}</h2></div>
      <button type="button" className={s.iconButton} aria-label="Cerrar configuración" onClick={() => dialog.current?.close()}>×</button>
    </div>
    <p className={s.muted}>Diseña el perfil del agente. Se guarda solo en esta demo; todavía no crea una IA ni ejecuta inversiones.</p>
    <form onSubmit={event => {
      event.preventDefault();
      if (!name.trim() || !description.trim()) return;
      const selectedStyle = styles.find(item => item.id === style)!;
      onSave({
        id: agent?.id ?? "custom", name: name.trim().toUpperCase(), role: `Estrategia de ${selectedStyle.label.toLowerCase()}`,
        style, color: selectedStyle.color, risk, horizon: agent?.horizon ?? "Por definir",
        description: description.trim(), looksFor: looksFor.trim() || "Criterios pendientes de definir.",
        avoids: avoids.trim() || "Límites pendientes de definir.",
      });
    }}>
      <label htmlFor="agent-name">Nombre del agente</label>
      <input id="agent-name" autoFocus required maxLength={18} value={name} onChange={event => setName(event.target.value)} placeholder="Ej. ORION" />
      <div className={s.formColumns}>
        <div><label htmlFor="agent-style">Forma de invertir</label><select id="agent-style" value={style} onChange={event => setStyle(event.target.value as AgentStyle)}>{styles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></div>
        <div><label htmlFor="agent-risk">Perfil de riesgo</label><select id="agent-risk" value={risk} onChange={event => setRisk(event.target.value as Risk)}>{["Conservador", "Moderado", "Agresivo"].map(item => <option key={item}>{item}</option>)}</select></div>
      </div>
      <label htmlFor="agent-thesis">¿Cómo piensa este agente?</label>
      <textarea id="agent-thesis" required rows={3} maxLength={240} value={description} onChange={event => setDescription(event.target.value)} placeholder="Describe qué busca, qué prioriza y qué evita." />
      <label htmlFor="agent-priorities">Qué prioriza</label>
      <input id="agent-priorities" maxLength={160} value={looksFor} onChange={event => setLooksFor(event.target.value)} placeholder="Ej. negocios rentables con caja estable" />
      <label htmlFor="agent-limits">Qué evita o cuestiona</label>
      <input id="agent-limits" maxLength={160} value={avoids} onChange={event => setAvoids(event.target.value)} placeholder="Ej. concentración excesiva en un solo sector" />
      <div className={s.dialogActions}><button type="button" className={s.secondaryButton} onClick={() => dialog.current?.close()}>Volver</button><button className={s.primaryButton} type="submit">Guardar perfil local</button></div>
    </form>
  </dialog>;
}
