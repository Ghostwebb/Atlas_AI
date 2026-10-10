"use client";

import { useEffect, useState, type CSSProperties } from "react";
import AgentGlyph from "./AgentGlyph";
import { initialAgents, type Decision } from "./agents-data";
import s from "./agents.module.css";

const durations = [2400, 3200, 2800, 3800];
export default function CommitteeDeliberation({ decision, onComplete }: { decision: Decision; onComplete: () => void }) {
  const [elapsed, setElapsed] = useState(0);
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    const start = performance.now();
    const timer = window.setInterval(() => setElapsed(performance.now() - start), 80);
    const done = window.setTimeout(onComplete, 6500);
    return () => { clearInterval(timer); clearTimeout(done); media.removeEventListener("change", update); };
  }, [onComplete]);
  const phase = elapsed < 4200 ? "reading" : elapsed < 5000 ? "merging" : elapsed < 5500 ? "core" : elapsed < 6500 ? "expanding" : "done";
  const status = { reading: "Los cuatro agentes preparan sus propuestas de ejemplo.", merging: "Propuestas completas. El comité converge.", core: "Las perspectivas se fusionan en un núcleo.", expanding: "ATLAS integra las perspectivas.", done: "Decisión de ejemplo disponible." }[phase];
  return <section className={s.deliberation} aria-label="Deliberación simulada del comité">
    <div className={s.sectionHeading}><h2>Del comité a ATLAS</h2><span className={s.demoPill}>SIMULACIÓN</span></div>
    <p className={s.muted}>Barras temporizadas de demostración. No representan análisis ni progreso real.</p>
    <p className={s.phaseStatus} role="status">{status}</p>
    <div className={s.deliberationStage} data-phase={phase} data-reduced={reduced}>
      <div className={s.deliberationAgents} aria-hidden={phase !== "reading"}>
        {initialAgents.map((agent, index) => {
          const progress = Math.min(100, Math.floor(elapsed / durations[index] * 100));
          return <article className={s.deliberationAgent} key={agent.id} style={{ "--agent-color": agent.color } as CSSProperties}>
            <span className={s.smallAvatar}><AgentGlyph style={agent.style}/></span><h3>{agent.name}</h3><p>{agent.role}</p>
            <label htmlFor={`sim-${agent.id}`}>Progreso simulado · {progress}%</label><progress id={`sim-${agent.id}`} max={100} value={progress}/><small>{progress === 100 ? "Propuesta de ejemplo lista" : "Preparando ejemplo…"}</small>
          </article>;
        })}
      </div>
      {(phase === "core" || phase === "expanding" || phase === "done") && <div className={s.fusedPanel}>
        <span className={s.fusedGlyph}><AgentGlyph mother/></span>
        {phase !== "core" && <><p className={s.overline}>IA MADRE · EJEMPLO</p><h2>ATLAS</h2>{phase === "done" ? <><strong>{decision.title}</strong><p>{decision.reason}</p><small>Resultado escrito para esta demo. Sin ejecución de inversiones.</small></> : <p>Integrando argumentos, riesgos y desacuerdos…</p>}</>}
      </div>}
    </div>
  </section>;
}
