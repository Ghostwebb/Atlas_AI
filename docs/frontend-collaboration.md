# Frontend: approved design and how we split the work

This branch publishes the approved dashboard design (light, soft-shadow style) with the
narrative report panel wired to `POST /api/report`. It is based on `main` after Phases 3 and 4.
Paper trading (PR #3) is **not** included and is not merged.

## What is in the approved frontend

| File | Content |
|---|---|
| `frontend/app/page.tsx` | Approved dashboard: sidebar, header search (`/api/analyze`), report panel, dashboard cards |
| `frontend/components/NarrativePanel.tsx` | Explicit "Generar informe" request to `/api/report` (es): loading and error states, generated vs deterministic label, synthetic-data notice, sections (reasons, counterpoints, risks, data gaps, limitations) with evidence ids |
| `frontend/app/globals.css` | Approved styles and layout |
| `frontend/app/layout.tsx` | Root layout |
| `frontend/.env.example` | `NEXT_PUBLIC_API_URL` (now tracked; `.gitignore` had hidden it) |

Data rules kept by this branch:
- The recommendation, confidence and supervisor status come from the backend response.
  They are never parsed from model text, and nothing is shown before an analysis exists (`—`).
- Net worth, investments, cash balance, market tiles and "Insight score" points are decorative.
  They are labeled **Demo data** on screen.
- The analysis card and the report show the synthetic-dataset notice.
- No button places, confirms or cancels orders.

`frontend/components/AnalysisPanel.tsx`, `ResultCard.tsx` and `lib/format.ts` (Phase 2 detail
view) remain in the repo but the approved page does not use them yet.

## Run it

```bash
# Backend (terminal 1)
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --port 8000

# Frontend (terminal 2)
cd frontend
cp .env.example .env.local      # optional; default is http://localhost:8000
npm install
npm run dev                     # http://localhost:3000
```

On Windows use `.venv\Scripts\pip` and `.venv\Scripts\uvicorn`. No keys are needed: the analysis
uses the synthetic demo dataset, and the report falls back to the deterministic version unless
LM Studio is configured on the backend (see `docs/phase-4-narration.md`). The page loads the
Nunito Sans font from Google Fonts; without internet it falls back to the system font.

Checks before every PR:

```bash
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

## Initial split

| Who | Area | Rule |
|---|---|---|
| Friend (frontend) | New components and styles in `frontend/components/paper/` | Simulated data only, following `docs/phase-5-paper-trading.md` once PR #3 is merged. No real API calls that place orders |
| Backend | PR #3 fixes (paper trading reservations) and new endpoints | Only `backend/` and `docs/` |
| Both | Shared dashboard files: `frontend/app/page.tsx`, `frontend/app/globals.css`, `frontend/lib/*` | Changed only through a small PR that the other person reviews, to avoid conflicts |

Paper trading UI guidance (permanent "Paper Trading — dinero ficticio" label, review screen,
explicit confirmation, uncertain state without a resend button) is in
`docs/phase-5-paper-trading.md`.

## Getting the branch and starting your own

```bash
git clone https://github.com/Ghostwebb/Atlas_AI.git   # or: git fetch origin
cd Atlas_AI
git fetch origin
git switch -c feat/paper-ui origin/feat/frontend-approved-design
# ... work only in frontend/components/paper/ ...
git push -u origin feat/paper-ui                      # then open a PR
```

Once `feat/frontend-approved-design` is merged into `main`, update your branch with
`git fetch origin && git rebase origin/main`, and target your PR at `main`.
