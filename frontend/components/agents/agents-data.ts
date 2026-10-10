export type AgentStyle = "value" | "growth" | "momentum" | "defensive";
export type Risk = "Conservador" | "Moderado" | "Agresivo";
export interface InvestmentAgent {
  id: string;
  name: string;
  role: string;
  style: AgentStyle;
  color: string;
  risk: Risk;
  horizon: string;
  description: string;
  looksFor: string;
  avoids: string;
}
export interface AgentProposal {
  agentId: string;
  symbol: string;
  action: "Comprar" | "Esperar";
  thesis: string;
  caution: string;
  evidence: string;
}
export interface Decision {
  symbol: string;
  title: string;
  reason: string;
  selectedAgentId: string;
  tradeoff: string;
}
export interface CommitteeFixture {
  id: string;
  name: string;
  market: string;
  proposals: AgentProposal[];
  decision: Decision;
}

// Proposed identities and authored examples, not running AI agents or market data.
export const initialAgents: InvestmentAgent[] = [
  {
    id: "argo", name: "ARGO", role: "El inversor de valor", style: "value", color: "#7863cd",
    risk: "Moderado", horizon: "Largo plazo",
    description: "Busca negocios sólidos que el mercado podría estar infravalorando.",
    looksFor: "Calidad del negocio, generación de caja y margen de seguridad.",
    avoids: "Pagar una prima que los fundamentales no justifican.",
  },
  {
    id: "nova", name: "NOVA", role: "La exploradora de crecimiento", style: "growth", color: "#337d78",
    risk: "Agresivo", horizon: "Medio / largo plazo",
    description: "Encuentra empresas con espacio para crecer y transformar su sector.",
    looksFor: "Expansión de ingresos, innovación y ventajas competitivas.",
    avoids: "Confundir una historia atractiva con crecimiento sostenible.",
  },
  {
    id: "vector", name: "VECTOR", role: "El lector de tendencias", style: "momentum", color: "#a56c32",
    risk: "Agresivo", horizon: "Corto / medio plazo",
    description: "Lee la dirección del mercado y busca movimientos con continuidad.",
    looksFor: "Tendencia, volumen y confirmación de señales técnicas.",
    avoids: "Entrar tarde en un movimiento sin confirmación.",
  },
  {
    id: "aegis", name: "AEGIS", role: "El guardián del capital", style: "defensive", color: "#566b9e",
    risk: "Conservador", horizon: "Según exposición",
    description: "Cuestiona cada propuesta y pone la preservación del capital primero.",
    looksFor: "Diversificación, liquidez y exposición controlada.",
    avoids: "Concentración excesiva y pérdidas difíciles de recuperar.",
  },
];

export const committeeFixtures: CommitteeFixture[] = [
  {
    id: "balanced", name: "Oportunidad equilibrada", market: "Objetivo: equilibrio entre oportunidad y riesgo",
    proposals: [
      { agentId: "argo", symbol: "AAPL", action: "Comprar", thesis: "Priorizar calidad y disciplina de valoración.", caution: "Revisar el margen de seguridad antes de entrar.", evidence: "Ejemplo: caja estable y ventaja competitiva." },
      { agentId: "nova", symbol: "NVDA", action: "Comprar", thesis: "Dar prioridad al potencial de expansión.", caution: "La valoración podría anticipar demasiado crecimiento.", evidence: "Ejemplo: demanda estructural y capacidad de expansión." },
      { agentId: "vector", symbol: "MSFT", action: "Comprar", thesis: "Esperar continuidad de una tendencia confirmada.", caution: "Un giro del mercado invalidaría la entrada.", evidence: "Ejemplo: tendencia y volumen alineados." },
      { agentId: "aegis", symbol: "AAPL", action: "Esperar", thesis: "Validar la exposición total antes de comprometer capital.", caution: "Varias propuestas concentran el mismo sector.", evidence: "Ejemplo: concentración tecnológica en la cartera." },
    ],
    decision: { symbol: "AAPL", title: "Priorizar calidad. Entrar con condiciones.", selectedAgentId: "argo",
      reason: "La propuesta de ARGO encaja mejor con el objetivo de equilibrio. ATLAS incorpora la objeción de AEGIS y condiciona cualquier entrada a revisar la exposición.",
      tradeoff: "Se deja pasar parte del potencial de crecimiento de NOVA para reducir la dependencia de expectativas futuras." },
  },
  {
    id: "defensive", name: "Capital primero", market: "Objetivo: preservar capital ante señales contradictorias",
    proposals: [
      { agentId: "argo", symbol: "AAPL", action: "Esperar", thesis: "La calidad no basta sin margen de seguridad.", caution: "Falta una valoración actualizada.", evidence: "Ejemplo: evidencia de valoración incompleta." },
      { agentId: "nova", symbol: "NVDA", action: "Comprar", thesis: "El crecimiento mantiene una tesis interesante.", caution: "La oportunidad exige asumir volatilidad elevada.", evidence: "Ejemplo: expansión potencial con incertidumbre." },
      { agentId: "vector", symbol: "MSFT", action: "Esperar", thesis: "Las señales todavía no confirman una dirección.", caution: "La entrada anticiparía una confirmación inexistente.", evidence: "Ejemplo: tendencia sin confirmación de volumen." },
      { agentId: "aegis", symbol: "—", action: "Esperar", thesis: "Conservar liquidez mientras se resuelven los desacuerdos.", caution: "Esperar también puede tener un coste de oportunidad.", evidence: "Ejemplo: exposición alta y evidencia contradictoria." },
    ],
    decision: { symbol: "Sin entrada", title: "Esperar también es una decisión.", selectedAgentId: "aegis",
      reason: "ATLAS prioriza la objeción de AEGIS: faltan confirmaciones y la exposición ya es elevada. Ninguna propuesta de compra supera las condiciones del objetivo conservador.",
      tradeoff: "Se acepta perder una posible subida a cambio de conservar flexibilidad y capital." },
  },
];
