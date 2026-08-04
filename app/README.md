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
| `POST /api/inverse` | submit a monolithic CST-Newton inverse solve; returns `job_id` (202) |
| `GET /api/inverse/{job_id}` | poll job status/result |

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
the extended system square, FM-1) that is out of scope for this phase. This
is exactly why the frontend Inverse view is marked "coming with T8" — the
backend job API (submit/poll, streamed-looking via polling, residual
history, release-and-verify) is real and already wired to it, but the target
input is fixed to "recover this NACA code" until that machinery lands.

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

- **Analyze view** (`app/frontend/src/app/analyze/page.tsx`): NACA code +
  alpha + Re + optional forced-trip form -> calls `/api/analyze` -> renders a
  Cp-vs-x/c chart (inverted y-axis, aero convention; upper/lower surfaces
  color-distinguished) and the airfoil outline.
- **Inverse view** (`app/frontend/src/app/inverse/page.tsx`): stub banner
  ("coming with T8") + a real submit-and-poll flow against
  `/api/inverse`/`/api/inverse/{job_id}`, showing the residual-history curve
  and release-and-verify result as the self-consistency solve runs.
- **Charts**: hand-built inline SVG, not a charting library. Justification is
  in a comment at the top of `app/frontend/src/components/CpChart.tsx` —
  short version: exactly two static XY curves per view, no
  brushing/zooming/interactive-target-drawing yet (that's deferred to the
  real Inverse UX, see above), so a charting library's dependency weight and
  default-axis fighting (aero's inverted Cp axis) buys nothing over a
  ~150-line SVG scale helper. Revisit (likely visx, lower-level/composable)
  when target-Cp drawing/brushing lands.

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
- Vercel/Render (or any) deployment — this phase is local-dev only.
- Target-Cp drawing/upload editor and any UI for `station_selection`/
  `alpha_free`/constraint editing beyond what `/api/presolve`'s JSON contract
  already exposes.
- Raw user-drawn Cp target mode for `/api/inverse` (see above).
- Streaming `/api/inverse` progress over SSE/WebSocket — phase 1 uses polling
  (`GET /api/inverse/{job_id}`); the PRD's "streams D-1/D-6 diagnostics"
  requirement (FR-5) is satisfied here by a full diagnostics-summary array
  returned once the job completes, polled at a fixed interval from the
  frontend, not a live per-iteration push. Revisit with SSE if/when true
  per-iteration streaming is needed.
- Cascade (pitch/stagger/periodicity) inputs, MISES-backed transonic solve,
  multi-user collaboration, public gallery — all explicitly "Later" in
  `docs/PRD.md` §3.5.
- Load testing / multi-worker scaling (NFR-6) — the in-process job store and
  `MFOIL_LOCK` above are single-worker-only by construction; sharding across
  workers needs an external job queue (e.g. Redis/RQ), not attempted here.
