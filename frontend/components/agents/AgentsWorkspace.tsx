"use client";

import { useCallback, useRef, useState, type CSSProperties } from "react";
import Link from "next/link";
import AgentGlyph from "./AgentGlyph";
import AgentEditor from "./AgentEditor";
import CommitteeDeliberation from "./CommitteeDeliberation";
import { committeeFixtures, initialAgents, type InvestmentAgent } from "./agents-data";
import s from "./agents.module.css";

type View = "committee" | "comparison" | "activity";
type Activity = { id: number; title: string; detail: string };

function NavIcon({ name }: { name: "home" | "agents" | "portfolio" | "settings" }) {
  const paths = {
    home: "m3 10 9-7 9 7M5 9v11h5v-6h4v6h5V9",
    agents: "M9 8a3 3 0 1 0 6 0 3 3 0 0 0-6 0ZM5 21v-3a7 7 0 0 1 14 0v3M3 6h2M19 6h2M2 13h3M19 13h3",
    portfolio: "M4 7h16v14H4zM8 7V3h8v4M4 12h16M10 12v3h4v-3",
    settings: "M4 7h16M4 17h16M8 4v6M16 14v6",
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}

export default function AgentsWorkspace() {
  const [agents, setAgents] = useState(initialAgents);
  const [fixtureId, setFixtureId] = useState("balanced");
  const [view, setView] = useState<View>("committee");
  const [selectedId, setSelectedId] = useState("argo");
  const [editor, setEditor] = useState<InvestmentAgent | "new" | null>(null);
  const [deliberating, setDeliberating] = useState(false);
  const [decided, setDecided] = useState(false);
  const [run, setRun] = useState(0);
  const [activity, setActivity] = useState<Activity[]>([]);
  const busy = useRef(false);
  const counter = useRef(0);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const decisionHeading = useRef<HTMLHeadingElement>(null);
  const fixture = committeeFixtures.find(item => item.id === fixtureId)!;
  const selected = agents.find(agent => agent.id === selectedId) ?? agents[0];
  const selectedProposal = fixture.proposals.find(proposal => proposal.agentId === selected.id);
  const originalProfiles = agents.length === initialAgents.length && agents.every((agent, index) => agent === initialAgents[index]);
  const canCompare = originalProfiles && !deliberating;

  function log(title: string, detail: string) {
    const entry = { id: ++counter.current, title, detail };
    setActivity(items => [entry, ...items]);
  }

  const completeDeliberation = useCallback(() => {
    setDecided(true); setDeliberating(false); busy.current = false;
    setActivity(items => [{ id: ++counter.current, title: "Decisión de ejemplo disponible", detail: fixture.decision.title }, ...items]);
  }, [fixture]);
  function compare() {
    if (busy.current || !canCompare) return;
    busy.current = true; setView("committee"); setRun(value => value + 1);
    setDeliberating(true); setDecided(false);
    log("Deliberación simulada iniciada", "Barras temporizadas de demostración, sin análisis real.");
  }

  function selectAgent(id: string) {
    setSelectedId(id);
    detailHeading.current?.focus();
  }

  return <div className={s.shell} lang="es">
    <aside className={s.sidebar} aria-label="Navegación del espacio de agentes">
      <Link href="/" className={s.brand} aria-label="ATLAS AI · volver al dashboard"><span className={s.brandMark}><AgentGlyph mother /></span><strong>ATLAS<span>AI</span></strong></Link>
      <div className={s.workspace}><span className={s.workspaceAvatar}>A</span><div><strong>Atlas workspace</strong><small>Investment intelligence</small></div></div>
      <p className={s.navLabel}>WORKSPACE</p>
      <nav className={s.nav}>
        <Link href="/"><NavIcon name="home"/>Dashboard</Link>
        <a href="#committee" className={s.navActive} aria-current="page" onClick={() => setView("committee")}><NavIcon name="agents"/>Agentes IA<span className={s.navCount}>{agents.length}</span></a>
        <button onClick={() => setView("comparison")}><NavIcon name="portfolio"/>Propuestas</button>
        <button onClick={() => setView("activity")}><NavIcon name="settings"/>Actividad local</button>
      </nav>
      <div className={s.sidebarBottom}><div className={s.systemNote}><span className={s.statusDot}/><strong>Un comité. Varias perspectivas.</strong><p>La decisión se entiende mejor cuando puedes ver el desacuerdo.</p></div><div className={s.profile}><span>AW</span><div><strong>Atlas workspace</strong><small>Prototipo de diseño</small></div></div></div>
    </aside>

    <main className={s.main} id="committee">
      <header className={s.header}>
        <div><p className={s.breadcrumb}>WORKSPACE <span>/</span> AGENTES IA</p><h1>Tu comité de inversión<span>.</span></h1><p className={s.subtitle}>Diferentes formas de pensar. Una decisión con criterio.</p></div>
        <button className={s.primaryButton} onClick={() => setEditor("new")} disabled={deliberating}><span aria-hidden="true">+</span> Diseñar agente</button>
      </header>

      <div className={s.demoNotice}><span className={s.demoPill}>VISTA DE DISEÑO</span><p>Perfiles propuestos y decisiones de ejemplo. Las IA todavía no están conectadas y no se ejecutan inversiones.</p></div>

      <section className={s.flow} aria-label="Cómo funciona el comité">
        <div><span className={s.stepNumber}>01</span><div><strong>Cada agente analiza</strong><small>Su estrategia, su perspectiva</small></div></div><span className={s.flowArrow} aria-hidden="true">→</span>
        <div><span className={s.stepNumber}>02</span><div><strong>Las propuestas se contrastan</strong><small>Coincidencias y desacuerdos</small></div></div><span className={s.flowArrow} aria-hidden="true">→</span>
        <div><span className={`${s.stepNumber} ${s.finalStep}`}>03</span><div><strong>ATLAS toma una decisión</strong><small>Con razones y condiciones</small></div></div>
      </section>

      <div className={s.toolbar}>
        <div className={s.viewSwitcher} role="group" aria-label="Vista del espacio de agentes">
          {([ ["committee", "El comité"], ["comparison", "Comparación"], ["activity", "Actividad"] ] as [View, string][]).map(([id, label]) => <button key={id} aria-pressed={view === id} className={view === id ? s.selectedView : ""} onClick={() => setView(id)}>{label}</button>)}
        </div>
        <div className={s.scenarioControl}><label htmlFor="example-case">Caso de ejemplo</label><select id="example-case" value={fixtureId} disabled={deliberating} onChange={event => { setFixtureId(event.target.value); setDecided(false); log("Caso de ejemplo cambiado", committeeFixtures.find(item => item.id === event.target.value)!.name); }}>{committeeFixtures.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
      </div>

      {(deliberating || decided) && <CommitteeDeliberation key={run} decision={fixture.decision} onComplete={completeDeliberation}/> }
      <div className={s.workspaceGrid}>
        <div className={s.primaryColumn}>
          {view === "committee" && <>
            <section aria-labelledby="agents-title">
              <div className={s.sectionHeading}><div><p className={s.overline}>INTELIGENCIA ESPECIALIZADA</p><h2 id="agents-title">Una personalidad para cada estrategia</h2></div><span className={s.countLabel}>{agents.length} perfiles</span></div>
              <div className={s.agentGrid}>
                {agents.map(agent => {
                  const proposal = fixture.proposals.find(item => item.agentId === agent.id);
                  const validProposal = initialAgents.includes(agent) ? proposal : undefined;
                  return <article key={agent.id} className={`${s.agentCard} ${selectedId === agent.id ? s.selectedAgent : ""}`} style={{ "--agent-color": agent.color } as CSSProperties}>
                    <div className={s.agentTop}><span className={s.agentAvatar}><AgentGlyph style={agent.style}/></span><span className={s.agentStatus}>{validProposal ? "Perfil de ejemplo" : "Sin conectar"}</span><button className={s.iconButton} aria-label={`Configurar ${agent.name}`} disabled={deliberating} onClick={() => setEditor(agent)}><NavIcon name="settings"/></button></div>
                    <h3>{agent.name}</h3><p className={s.agentRole}>{agent.role}</p><p className={s.agentDescription}>{agent.description}</p>
                    <div className={s.agentTraits}><span>{agent.risk}</span><span>{agent.horizon}</span></div>
                    <div className={s.proposalStrip}><div><span>PROPUESTA DE EJEMPLO</span><strong>{validProposal ? validProposal.symbol : "Por generar"}</strong></div><span className={validProposal?.action === "Comprar" ? s.buyTag : s.waitTag}>{validProposal?.action ?? "Pendiente"}</span></div>
                    <button className={s.reasoningButton} aria-pressed={selectedId === agent.id} onClick={() => selectAgent(agent.id)}>Explorar razonamiento <span aria-hidden="true">↗</span></button>
                  </article>;
                })}
              </div>
            </section>

            <section className={s.detailPanel} aria-labelledby="agent-detail-title">
              <div className={s.sectionHeading}><div><p className={s.overline}>DENTRO DE SU ESTRATEGIA</p><h2 id="agent-detail-title" ref={detailHeading} tabIndex={-1}>Así piensa {selected.name}</h2></div><span className={s.detailGlyph} style={{ color: selected.color }}><AgentGlyph style={selected.style}/></span></div>
              <div className={s.detailColumns}><div><h3>Lo que busca</h3><p>{selected.looksFor}</p></div><div><h3>Lo que cuestiona</h3><p>{selected.avoids}</p></div></div>
              {selectedProposal && initialAgents.includes(selected) ? <div className={s.thesis}><span className={s.quoteMark} aria-hidden="true">“</span><div><p>{selectedProposal.thesis}</p><small>{selectedProposal.caution}</small></div></div> : <p className={s.emptyHint}>Este perfil necesita criterios y una propuesta propios. El diseño no genera análisis automáticamente.</p>}
            </section>
          </>}

          {view === "comparison" && <section className={s.comparisonPanel} aria-labelledby="comparison-title"><div className={s.sectionHeading}><div><p className={s.overline}>UNA MESA, VARIAS TESIS</p><h2 id="comparison-title">¿Dónde están de acuerdo?</h2></div><span className={s.demoPill}>Ejemplo</span></div><p className={s.muted}>ATLAS compara argumentos; una mayoría de votos no basta para elegir.</p><div className={s.comparisonList}>{agents.map(agent => {
            const proposal = initialAgents.includes(agent) ? fixture.proposals.find(item => item.agentId === agent.id) : undefined;
            return <article className={s.comparisonRow} key={agent.id}><div className={s.comparisonIdentity}><span className={s.smallAvatar} style={{ color: agent.color }}><AgentGlyph style={agent.style}/></span><div><h3>{agent.name}</h3><p>{agent.role}</p></div><span className={proposal?.action === "Comprar" ? s.buyTag : s.waitTag}>{proposal?.action ?? "Pendiente"} {proposal?.symbol}</span></div><p>{proposal?.thesis ?? "Sin propuesta: falta conectar este perfil."}</p>{proposal && <div className={s.evidence}><span>Argumento de ejemplo</span><p>{proposal.evidence}</p><span>Objeción</span><p>{proposal.caution}</p></div>}</article>;
          })}</div></section>}

          {view === "activity" && <section className={s.activityPanel} aria-labelledby="activity-title"><div className={s.sectionHeading}><div><p className={s.overline}>TRAZABILIDAD</p><h2 id="activity-title">El recorrido de una decisión</h2></div><span className={s.demoPill}>Sesión local</span></div>{activity.length ? <ol className={s.activityList}>{activity.map(item => <li key={item.id}><span className={s.activityNumber}>{String(item.id).padStart(2, "0")}</span><div><h3>{item.title}</h3><p>{item.detail}</p></div></li>)}</ol> : <div className={s.emptyState}><span className={s.emptyIcon}><AgentGlyph mother/></span><h3>El comité aún no ha deliberado</h3><p>Compara las propuestas de ejemplo para ver cómo quedaría el registro de una decisión.</p><button className={s.secondaryButton} disabled={!canCompare} onClick={compare}>Comparar propuestas de ejemplo</button></div>}</section>}
        </div>

        <aside className={s.motherColumn} aria-label="IA madre y decisión del comité">
          <section className={s.motherCard}>
            <div className={s.motherTop}><span className={s.overline}>LA VISIÓN COMPLETA</span><span className={s.motherTag}>IA MADRE</span></div>
            <div className={`${s.coreVisual} ${deliberating ? s.coreWorking : ""}`} aria-hidden="true"><div className={s.orbitOne}/><div className={s.orbitTwo}/><span className={s.orbitPoint}/><div className={s.core}><AgentGlyph mother/></div></div>
            <div className={s.motherIdentity}><p className={s.overline}>DIRECTORA DEL COMITÉ</p><h2>ATLAS</h2><p>Escucha cada tesis.<br/>Decide con el contexto completo.</p></div>
            <div className={s.motherCriteria}><div><span>01</span><p>Contrasta argumentos y evidencia</p></div><div><span>02</span><p>Evalúa riesgos y desacuerdos</p></div><div><span>03</span><p>Elige, condiciona o decide esperar</p></div></div>
            <div className={s.objective}><span>OBJETIVO DEL CASO</span><p>{fixture.market.replace("Objetivo: ", "")}</p></div>
            <button className={s.primaryButton} disabled={!canCompare} onClick={compare}>{deliberating ? "Contrastando propuestas…" : decided ? "Repetir ejemplo" : "Comparar propuestas"}<span aria-hidden="true">↗</span></button>
            <p className={s.motherFootnote}>{originalProfiles ? "Deliberación simulada · sin órdenes ni conexión a modelos" : "Has cambiado el comité. Los ejemplos originales ya no son válidos para estos perfiles."}</p>
            {!originalProfiles && <button className={s.textButton} disabled={deliberating} onClick={() => { setAgents(initialAgents); setSelectedId("argo"); setDecided(false); log("Perfiles de ejemplo restaurados", "Restauración local del comité inicial."); }}>Restaurar comité de ejemplo</button>}
          </section>

          <section className={s.decisionCard} aria-labelledby="decision-title" aria-busy={deliberating}>
            <div className={s.sectionHeading}><p className={s.overline}>DECISIÓN CENTRAL</p><span className={s.statusDot}/></div>
            <div role="status" aria-live="polite">
              {deliberating ? <><div className={s.loadingBar}/><h2 id="decision-title">Escuchando las distintas perspectivas</h2><p>Comparando oportunidad, riesgo y condiciones del caso de ejemplo.</p></> : decided ? <><span className={s.decisionSymbol}>{fixture.decision.symbol}</span><h2 id="decision-title" ref={decisionHeading} tabIndex={-1}>{fixture.decision.title}</h2><p>{fixture.decision.reason}</p><div className={s.chosenAgent}><span>TESIS PRIORIZADA</span><strong>{agents.find(agent => agent.id === fixture.decision.selectedAgentId)?.name}</strong></div><details className={s.tradeoff}><summary>¿Qué se deja de lado?</summary><p>{fixture.decision.tradeoff}</p></details><p className={s.decisionDisclaimer}>Resultado escrito para esta demo. No es una recomendación real ni autoriza una inversión.</p></> : <><h2 id="decision-title">Primero las ideas.<br/>Después la decisión.</h2><p>Aquí verás la propuesta elegida, sus condiciones y por qué las alternativas quedaron atrás.</p><span className={s.pendingLabel}>Pendiente de deliberación de ejemplo</span></>}
            </div>
          </section>
        </aside>
      </div>
      <footer className={s.footer}><span>ATLAS AI · Inteligencia que puedes entender.</span><span>Diseño conceptual · Sin ejecución de inversiones</span></footer>
    </main>

    {editor && <AgentEditor agent={editor === "new" ? undefined : editor} onDismiss={() => setEditor(null)} onSave={agent => {
      const newAgent = editor === "new" ? { ...agent, id: `custom-${++counter.current}` } : agent;
      setAgents(items => editor === "new" ? [...items, newAgent] : items.map(item => item.id === agent.id ? agent : item));
      setSelectedId(newAgent.id);
      setDecided(false);
      log(editor === "new" ? "Perfil diseñado" : "Perfil actualizado", `${newAgent.name} · ${newAgent.role}. Sin conexión a una IA.`);
      setEditor(null);
    }}/>}
  </div>;
}
