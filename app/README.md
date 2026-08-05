# CINS app — phase 1 (backend-first, local dev)

Full-stack shell around the `cins` engine core (`src/cins/`), per the "kundali"
architecture in [`docs/PRD.md`](../docs/PRD.md) §3.2:

```
Deterministic engine core (src/cins/ — cst, solver, diagnostics, benchmarks.pipeline)
        │  no I/O, no FastAPI/Next.js/Supabase dependency (NFR-1)
        ▼
FastAPI backend (app/backend/)
        │  /health, /api/analyze, /api/fit, /api/presolve, /api/inverse
        ▼
Next.js 14 App Router frontend (app/frontend/)
        │  Analyze view (working) · Inverse view (stub, wired to the job API)
        ▼
Supabase (auth, saved designs, RLS)  — NOT built in this phase, see "Deferred" below
```

The engine (`src/cins/`) is untouched by this phase — every array in/out of
`app/backend/app/engine.py` passes straight through to `cins.cst` /
`cins.solver` / `cins.benchmarks.pipeline` functions. See that module's
docstring for the exact call sequences reused from
`cins.benchmarks.pipeline.run_pipeline` (`prepare_cell` -> `InverseProblem`
-> `solve_inverse`).

## Run it

Backend (FastAPI, from the repo root — uses the repo's existing `.venv`):

```bash
# one-time: layer FastAPI/uvicorn onto the repo's .venv (already has cins + numpy/scipy/pydantic)
.venv/bin/python -m pip install -r app/backend/requirements.txt

# run (single worker — see "Concurrency" below)
.venv/bin/uvicorn app.main:app --reload --app-dir app/backend --port 8000
```

Frontend (Next.js 14 App Router):

```bash
cd app/frontend
npm install   # already run once by this phase's setup
npm run dev   # http://localhost:3000
```

The frontend proxies `/api/*` and `/health` to the backend origin
(`http://127.0.0.1:8000` by default; override with `CINS_BACKEND_ORIGIN`, see
`app/frontend/next.config.ts`) — the browser only ever talks to
`localhost:3000`.

Tests:

```bash
.venv/bin/python -m pytest app/backend/tests -q          # fast suite (default)
.venv/bin/python -m pytest app/backend/tests -q -m slow   # + viscous analyze + full inverse solve
cd app/frontend && npm run build && npm run lint
```

## API surface (phase 1)

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness |
| `POST /api/analyze` | direct mfoil solve (NACA code or coords) -> cl/cd/cm, Cp(x), converged, geometry |
| `POST /api/fit` | least-squares CST fit to supplied coordinates -> A_upper/A_lower, zeta_T, rms, gram_condition |
| `POST /api/presolve` | T4 linear pre-solve + realisability metric (ADR-0004) |
| `POST /api/inverse` | submit a self-consistency (`naca_target`) monolithic CST-Newton inverse solve; returns `job_id` (202) |
| `POST /api/inverse/gate` | T4 realisability gate only (no solve) for a user-defined target |
| `POST /api/inverse/raw` | submit a user-defined-target (`raw_target`) inverse solve; returns `job_id` (202) |
| `GET /api/inverse/{job_id}` | poll job status/result — shared by `/api/inverse` and `/api/inverse/raw` |
| `GET /api/airfoils` | UIUC corpus (123 sections, cached thickness/camber) + curated NACA presets |
| `GET /api/airfoils/{id}/geometry` | coordinates for `uiuc:<name>` or `naca:<code>` |
| `POST /api/geometry/from-cst` | instant CST coefficients -> coordinates + derived engineering parameters |
| `POST /api/flowfield` | inviscid velocity/Cp field on a grid, for vector/contour rendering |

`/api/fit` and `/api/geometry/from-cst` both return a `derived` block: LE
radius (`A_u0^2/2`), TE wedge half-angles (upper/lower, from the exact
TE-slope identity), max thickness/camber + their x-locations, and inscribed
area (Beta-function row) — all closed-form from the CST coefficients, no
quadrature (`app.engine.derived_geometry_quantities`).

Request/response shapes: `app/backend/app/schemas.py` (pydantic, mirrors
`cins` conventions — CST vectors `[A_u0..A_un, A_l0..A_ln]`, Cp in mfoil's
panel-node loop order unless split into `upper`/`lower`). Errors are
structured JSON via `HTTPException(detail=...)`; **realisability warnings are
not errors** — `/api/presolve` always returns 200 with `realisable: false`
when the target exceeds `presolve.realisability_threshold` (ADR-0004), it
never raises for that reason.

### `/api/presolve` and ADR-0004

The realisability number this endpoint returns is always **model 1**
(CST-representability against the model-consistent linearization,
`presolve.realisability` in `src/cins/solver/presolve.py`) — the response
field `realisability_label` states this explicitly
(`"inviscid-consistent (ADR-0004)"`). `model_gap` (ADR-0004's metric 2 — how
far the inviscid linearization sits from viscous physics) is reported as
`null` here: it needs a *matched* viscous baseline solve at the same
geometry, which only naturally exists inside `/api/inverse`'s own T4
pre-solve step (`init="presolve"`, see `prep.model_gap` in
`app/backend/app/engine.py::run_inverse`), not in a standalone presolve call.
This is a deliberate phase-1 scope cut, not an oversight — do not read a
`null` `model_gap` from `/api/presolve` as "no model gap exists."

### `/api/inverse`: self-consistency mode only

Phase 1 ships one inverse mode: **`naca_target`**, a T7-style
self-consistency solve — generate a target Cp from a NACA airfoil's own CST
fit, then recover it via the monolithic Newton solve
(`cins.benchmarks.pipeline.prepare_cell`). A raw, user-drawn target-Cp mode
is **not** implemented: it needs target-station correspondence machinery
(interpolating an arbitrary user curve onto mfoil panel nodes while keeping
the extended system square, FM-1). **This has since landed** — see
"`/api/inverse/raw` — user-defined target" below; this paragraph is kept for
history.

### `/api/inverse/raw` and `/api/inverse/gate` — user-defined target

A second inverse mode that accepts a target the user defines directly,
rather than one generated from a NACA code's own self-consistency Cp:

- `POST /api/inverse/gate` — runs ONLY the T4 presolve realisability gate
  (`app.engine.run_presolve_gate_raw`) against a `baseline` (NACA code or
  explicit CST coefficients) and a `target` (`x`, plus either `cp` or
  `ue_over_vinf` — converted via `Cp = 1-(u_e/V_inf)^2`, incompressible only).
  Always 200; a non-realisable target (ADR-0004) is a warning in the
  response, never an error, exactly like `/api/presolve`.
- `POST /api/inverse/raw` — submits the full monolithic Newton solve against
  that target as a background job (202 + `job_id`), reusing the **same**
  `GET /api/inverse/{job_id}` poll route as `/api/inverse`. The result's
  `presolve_gate` field always carries the T4 verdict, even on an early
  failure, so the UI can show the realisability warning regardless of
  outcome — this is the dossier §7.10 guard made into product UX.
- Constraint rows (`shared_le_radius`, `le_radius`, `te_wedge`, `area`) are
  optional in the request; if none is given, the endpoint auto-adds a
  `shared_le_radius` row with `b = g·A0` (the presolved initial guess) rather
  than an idealized value — the "target-consistent constraint RHS" lesson
  from T4 (`.remember/target-consistent-constraint-rhs.md`).
- `alpha_free` defaults to `true` (dossier FM-1 absorption DOF) — recommended
  for arbitrary targets since there is no natural alpha to fix against.
- **Scope cut vs. `/api/inverse`'s `naca_target` mode**: raw-target solves
  use `le_treatment: none` and **natural** (free) transition, not the
  dossier's "T7 winning configuration" (`prescribed` LE + forced trip,
  `.remember/t7-winning-configuration.md`) — there is no natural trip
  location to match for a user-drawn target. Empirically (manual runs during
  development, not yet a gate test) this converges correctly for
  self-consistent identity-case targets but can take many more Newton
  iterations (small trust-region steps) than the tuned T7 recipe for
  less-consistent targets; `newton.max_iter` (default 50) bounds the wait,
  and a non-convergent result is still returned honestly
  (`converged: false`) rather than fabricated. Retuning the trust-region /
  omega selection for this mode is deferred — see "Deferred" below.
- Coordinate import: `load_airfoil_dat` (Selig/Lednicer autodetect) backs
  `GET /api/airfoils/{id}/geometry` for `uiuc:<name>` ids, so any of the 123
  UIUC sections can be used as a baseline or as an analyze/fit target;
  arbitrary user-uploaded `.dat` files are not yet accepted directly (the
  frontend target editor instead lets you paste/upload a CSV of the target
  *Cp curve*, not raw coordinates — see "Deferred").

### Concurrency guard (ADR-0003)

`mfoil`'s forced-transition shim (`set_forced_transition`/
`release_transition`, `src/cins/solver/mfoil_adapter.py`) reassigns
**module-level** vendor functions — it is process-global, not
instance-scoped. `app/backend/app/engine.py::MFOIL_LOCK` (a plain
`threading.Lock`) is held around every code path that may install the shim:
the whole `/api/inverse` pipeline, and `/api/analyze` when
`transition.mode == "forced"`. A second inverse submission blocks on this
lock rather than running concurrently — "one inverse at a time" by
construction, not by a queue-length limit.

The `/api/inverse` job store (`app/backend/app/jobs.py`) is an **in-process
dict** — run with a single uvicorn worker (no `--workers`); it is not shared
across processes and does not survive a restart. This is intentional for
phase-1 local-dev scope, not an oversight.

## Frontend

- **Analyze view** (`app/frontend/src/app/analyze/page.tsx`): an airfoil
  browser panel (searchable UIUC list + curated NACA presets, via
  `/api/airfoils`) alongside the NACA-code/alpha/Re/forced-trip form -> calls
  `/api/analyze` -> renders a Cp-vs-x/c chart (inverted y-axis, aero
  convention), the airfoil outline, and a CST-derived engineering-parameter
  readout (LE radius, TE wedge, max t/c + location, max camber + location,
  inscribed area) fitted from the solved geometry via `/api/fit`.
- **Inverse view** (`app/frontend/src/app/inverse/page.tsx`): two modes.
  "Self-consistency (NACA target)" is the original submit-and-poll flow
  against `/api/inverse`/`/api/inverse/{job_id}`. "Custom target" (default)
  is the target editor: load a template Cp from any NACA code's own solve
  (via `/api/analyze`), edit it in a numeric table, or upload a CSV of
  `(x/c, Cp)` or `(x/c, u_e/V_inf)` rows; pick a baseline (NACA code);
  optionally fix a leading-edge radius constraint; toggle `alpha_free`; then
  either "Check realisability" (`/api/inverse/gate`, shown as a
  green/amber verdict card with the ADR-0004 warning text when applicable)
  or "Run inverse solve" (`/api/inverse/raw`), which polls the same job
  route and surfaces the realisability card again from the job result.
- **Charts**: hand-built inline SVG, not a charting library. Justification is
  in a comment at the top of `app/frontend/src/components/CpChart.tsx` —
  short version: static XY curves and simple tables, no
  brushing/zoom/drag-based curve editing yet (see "Deferred": a drag-based
  per-surface control-point editor is a larger follow-up over today's
  template-load + table-edit + CSV-upload editor), so a charting library's
  dependency weight and default-axis fighting (aero's inverted Cp axis) buys
  nothing over a ~150-line SVG scale helper.
- **Deliberately NOT built this pass** (see "Deferred"): a dedicated Flow
  Field view for `/api/flowfield` (the endpoint is live and tested but has
  no frontend consumer yet), a full "Airfoil Studio" with live CST-coefficient
  sliders morphing geometry via `/api/geometry/from-cst` (the endpoint is
  live; the Analyze page consumes `/api/fit`'s `derived` block but does not
  yet expose editable sliders), the animated per-iteration "Inverse Design
  Theater" (geometry/Cp/residual evolving together — the backend records
  only the final diagnostics summary, not per-iteration geometry snapshots),
  and a Results Gallery / `/api/showcase` replay of archived T7/T8 runs.

## Architecture notes

- `app/backend/app/engine.py` is the only module that calls into `cins`
  directly; routers (`app/backend/app/routers/*.py`) only translate
  HTTP <-> pydantic <-> engine calls.
- `app/backend/app/schemas.py`: pydantic v2 models, one section per endpoint.
- `app/backend/app/jobs.py`: the in-process job store described above.
- Nothing under `src/cins/`, `configs/`, or `docs/` was modified by this
  phase; `app/backend/requirements.txt` layers FastAPI/uvicorn/httpx onto the
  repo's existing `.venv` (already has `cins` installed editable plus
  numpy/scipy/pydantic/pyyaml from the root `pyproject.toml`).

## Deferred (explicitly out of scope for this phase)

- Supabase auth, saved designs, RLS (FR-10, NFR-4) — no database or auth
  exists yet; every endpoint above is unauthenticated and stateless (job
  store aside).
- Streaming `/api/inverse`/`/api/inverse/raw` progress over SSE/WebSocket —
  both use polling (`GET /api/inverse/{job_id}`); a full diagnostics-summary
  array is returned once the job completes, polled at a fixed interval from
  the frontend, not a live per-iteration push.
- **Per-iteration inverse "stages"** (geometry/Cp/residual snapshots at every
  Newton iteration, for an animated "Inverse Design Theater"): NOT
  implemented. `solve_inverse` (`src/cins/solver/newton.py`) and
  `NewtonDiagnostics` were deliberately left untouched this pass — the T8
  117-cell UIUC panel sweep was running against the current pipeline
  behavior when this work started, and the mission brief for this task
  explicitly asked to prefer not touching `pipeline.py`/the core solver.
  `diagnostics[]` in the job result still gives per-iteration scalar norms
  (`R_norm`, `T_norm`, `G_norm`, `cond_J`, ...), just not geometry/Cp arrays.
- `/api/showcase` (replay of archived `experiments/results/t7_naca2412` +
  `t8` panel cells + `figures/paper/*.png` as static, labeled-archived
  content) and a Results Gallery frontend view — not built.
- A Flow Field frontend view, live CST-slider morphing UI ("Airfoil Studio"),
  and a drag-based target-curve editor (control points, not just
  table/CSV) — the backing endpoints (`/api/flowfield`,
  `/api/geometry/from-cst`) exist and are tested, but have no dedicated
  frontend consumer yet beyond what's described above.
- Direct `.dat` coordinate **upload** (client picks a file, server parses via
  `load_airfoil_dat`) — the loader is wired up server-side for the UIUC
  corpus (`GET /api/airfoils/{id}/geometry`) but there is no upload endpoint
  for a brand-new file the user supplies; only a target-*Cp*-curve CSV
  upload exists (Inverse view).
- BL distributions (theta/delta*/cf/Hk vs x, transition marker) added to
  `/api/analyze`'s response for viscous solves — not implemented; `m.post`
  already carries these fields internally (`vendor/mfoil/mfoil.py`) but the
  endpoint/schema/frontend tabs were not built this pass.
- Newton trust-region/omega tuning for `/api/inverse/raw`'s
  `le_treatment: none` + free-transition configuration — see "Scope cut"
  note above; the dossier's tuned "T7 winning configuration" is
  `prescribed` LE + forced transition, which `naca_target` mode still uses.
- Cascade (pitch/stagger/periodicity) inputs, MISES-backed transonic solve,
  multi-user collaboration, public gallery — all explicitly "Later" in
  `docs/PRD.md` §3.5.
- Load testing / multi-worker scaling (NFR-6) — the in-process job store and
  `MFOIL_LOCK` above are single-worker-only by construction; sharding across
  workers needs an external job queue (e.g. Redis/RQ), not attempted here.

## Deploy

- **Backend**: `app/backend/Dockerfile` (build context = repo root, so it
  can copy `src/`, `vendor/`, `configs/`, `data/airfoils/` alongside the app
  package). `python:3.12-slim`, `pip install -e .` + `app/backend/requirements.txt`,
  single-worker `uvicorn` on `$PORT` (default `7860`, the Hugging Face
  Spaces Docker-SDK convention). Build/run:
  ```bash
  docker build -f app/backend/Dockerfile -t cins-backend .
  docker run -p 7860:7860 -e ALLOWED_ORIGINS=https://your-frontend.example cins-backend
  ```
  CORS origins are configurable via the `ALLOWED_ORIGINS` env var
  (comma-separated; defaults to `http://localhost:3000` for local dev —
  `app/backend/app/main.py`).
- **Frontend**: `app/frontend/next.config.ts` reads `NEXT_PUBLIC_API_BASE`
  for the backend origin the `/api`/`/health` rewrite proxies to, falling
  back to `CINS_BACKEND_ORIGIN` (back-compat) then `http://127.0.0.1:8000`.
  Set `NEXT_PUBLIC_API_BASE` to the deployed backend's origin (e.g. the HF
  Space URL) when deploying the frontend (Vercel or otherwise).
