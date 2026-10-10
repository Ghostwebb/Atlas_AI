# Agents workspace design

Preview: `/agents-preview`. Start from `frontend/` with `npm ci` and
`npm run dev -- --port 3010`.

This is the proposed agent committee UI, following the approved frontend's surfaces,
typography, spacing, shadows and purple accent. Dashboard and backend files are unchanged.

## Design

- ARGO: value; NOVA: growth; VECTOR: momentum; AEGIS: capital preservation.
- Each profile has its own identity, risk, horizon, investment philosophy and objections.
- ATLAS is the mother AI: compares theses, accounts for dissent, and chooses or waits.
- Views: committee, comparison and local activity.
- Local profile editor: name, strategy, risk, philosophy, priorities and limits.

Names and strategies are provisional design suggestions, not configured/running AI agents.
All proposals and decisions are authored fixtures in `agents-data.ts`. No investment,
model inference or external API call occurs. Changes last only for the current page session.
Editing/adding a profile invalidates the example committee's decision; the demo never
pretends a canned decision was produced for a changed strategy.

## Components and future connection

`AgentsWorkspace.tsx`: interactive preview controller and layout.
`AgentEditor.tsx`: native accessible dialog with save/dismiss callbacks.
`AgentGlyph.tsx`: vector identity system for agents and ATLAS.
`agents-data.ts`: typed profiles, proposals and decisions plus two deterministic cases.
`agents.module.css`: local styling.

`InvestmentAgent`, `AgentProposal`, `CommitteeFixture` and `Decision` describe the initial
UI data boundary. Real integration should add server ids, run states, evidence references,
data freshness, model provenance, errors and persisted agent configurations. Replace the
authored fixture/timeout with the orchestrator's output; do not infer decisions from UI names
or turn them into orders. Final strategy definitions and the mother's selection rules remain
to be specified with the team.

The existing Turbopack Tailwind rule emits plain CSS for module files. A minimal condition
in `next.config.ts` excludes `*.module.css`, preserving native scoped exports.

## Checks executed

- TypeScript, ESLint, production build.
- Desktop 1440 px and mobile 390 px: no document horizontal overflow.
- Committee selection and focused reasoning, comparison, activity, simulated deliberation
  with locked controls, balanced decision and defensive wait decision.
- Create a profile locally; decision invalidated and pending proposal displayed; restore
  original committee. Native dialog closes with Escape.

The initial typecheck found stale generated routes from the earlier paper branch.
`next typegen` regenerated these; the final typecheck passes. No dependency or shared
dashboard change is included. This branch deliberately does not contain the paper UI commit.
