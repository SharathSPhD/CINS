# PRD — CINS Product Requirements

Status: binding. Three tracks are built together, per [`CLAUDE.md`](../CLAUDE.md): science
(T0–T9, see [`docs/SPEC.md`](SPEC.md)), paper P1, and product (site + app). Gate discipline
for all three is [`docs/GATES.md`](GATES.md). Full technical background is the dossier
[`docs/CST_MISES_Monolithic_Inverse_Design.md`](CST_MISES_Monolithic_Inverse_Design.md).

---

## 1. Track A — Science (T0–T9)

Scope, tasks, and gate thresholds are fully specified in `docs/SPEC.md` §7 and are not
duplicated here. This PRD's role for Track A is only to state the product-level success
condition: **T7 (the falsifiable test) closes.** Everything upstream of T7 is
infrastructure; everything downstream (T8, T9) is evidence-gathering for the paper and
Stage 2 planning.

## 2. Track B — Paper P1

**Target venue:** AIAA Journal, or AIAA SciTech as a conference-paper first pass.

**Novelty claim (must appear verbatim in intent, not necessarily wording, in the paper's
introduction and abstract):**

> A complete, analytic geometry basis (CST) whose linearity makes the geometric Jacobian
> block exact and constant, combined with geometric design constraints expressed as linear
> algebraic rows, together convert constrained shape *optimization* into constrained
> *root-finding* — a square Newton system with flow state, CST coefficients, and angle of
> attack as joint unknowns.

**What this is explicitly NOT claiming, and must not be confused with in the text:**

| Claim this paper does NOT make | Why | Prior art |
|---|---|---|
| "Putting geometry unknowns in a Newton system is new" | It isn't | Drela, MIT GTL Report 187 (1986); Drela, AGARD-R-780 (1990) — MISES Modal-Inverse already does this with heuristic modes |
| "Using CST in inverse design is new" | It isn't | Morris, Allen & Rendall, AIAA 2010-1228 — CST used as a *smoother* on a pressure-residual-driven shape correction; CST is not a Newton unknown there, it post-processes a correction |

**What P1 does claim as new** (the combination, not any single piece): (a) the basis is
complete and analytic, so modes are not heuristic bumps; (b) constraints (LE radius, TE
wedge, area, curvature) become linear rows rather than penalty terms or non-smooth
predicates; (c) CST coefficients are directly interpretable as manufacturing/mechanical
constraints for turbine blades. See dossier §2 and §10 for the full positioning argument
and §5.6 for the negative-result literature check that must be re-verified against AIAA/ASME
Digital Collections before submission (not yet done as of this writing — treat as an open
item, not a settled claim).

**Evidence the paper needs (traces to T8/T9 and `docs/STATS_PROTOCOL.md`):**
- DOF accounting derivation and the `M + K = n_A + 1` assertion (T5).
- Conditioning curve `cond(GᵀG)` vs n (T2, FM-2 evidence).
- The falsifiable-test result and D-6 quadratic-tail figure (T7) — the headline figure.
- Flow-solve-count comparison against a tuned nested `scipy.least_squares` baseline (T8,
  H2 in `docs/STATS_PROTOCOL.md`).
- Ablation matrix results (T8, dossier §7.9).

**Growth discipline:** `paper/` grows at every gate closure (`docs/GATES.md` condition 5);
it is never written in one pass at the end.

## 3. Track C — Product

### 3.1 Progress site (GitHub Pages, `site/`)

Public-facing record of gate closures, figures, and the current state of the hypothesis
test. Updated at every gate (`docs/GATES.md` condition 5). Not a marketing site — a
lab-notebook site: task status, D-6 plots, links to closure reports in `docs/gates/`.

### 3.2 Full-stack app (`app/`)

**Architecture pattern: "kundali"** — a deterministic engine core with no I/O, wrapped by
progressively less pure layers:

```
Deterministic engine core (pure functions, no I/O)
        │  src/cins/{cst,solver,diagnostics}/ — reused directly, not reimplemented
        ▼
FastAPI backend
        │  endpoints below
        ▼
Next.js 14 App Router frontend (Vercel)
        │
        ▼
Supabase (auth, saved designs, RLS owner-only)
```

The engine core is exactly the `src/cins/` package built for Track A — the app is a thin
shell around it, not a reimplementation. This is a hard requirement: any drift between the
research engine and the app engine invalidates both the paper's reproducibility claim and
the app's correctness.

**Backend endpoints (FastAPI):**

| Endpoint | Purpose | Streaming |
|---|---|---|
| `POST /api/analyze` | Forward mfoil solve on a given geometry (direct mode) | no |
| `POST /api/fit` | Fit CST to an uploaded/selected airfoil (T2 `fit_cst`) | no |
| `POST /api/presolve` | Linear pre-solve + realisability metric (T4) | no |
| `POST /api/inverse` | Monolithic CST-Newton inverse solve from a target Cp | **yes** — streams per-iteration D-1/D-6 diagnostics as the Newton loop runs |
| `POST /api/realisability` | Realisability check only, no full inverse solve | no |

**Frontend (Next.js 14 App Router, Vercel):** draw/upload a target Cp distribution, submit
to `/api/inverse`, watch convergence live (streamed diagnostics), inspect the resulting
geometry and realisability warnings, save designs.

**Supabase:** auth, saved-design storage, Row Level Security scoped to owner-only access —
no cross-user visibility on saved designs by default.

### 3.3 Competitive analysis

| Product | What it does | Category |
|---|---|---|
| foil.tools | NeuralFoil + CST parameterisation, browser-based airfoil *analysis* | Forward analysis |
| airfoilx.com | NACA generator + NeuralFoil + BEM | Forward analysis / generation |
| Webfoil (U-Mich MDO Lab) | Airfoil analysis and optimization tooling | Forward analysis / optimization |
| NeuralFoil itself | ML surrogate for XFOIL-like forward analysis | Forward analysis (ML) |
| airfoiltools.com | Airfoil database + XFOIL-based forward analysis | Forward analysis |

**Every one of these is forward-analysis, or optimization/ML-based.** None offers
deterministic monolithic inverse design: draw a target Cp, get geometry back via a square
Newton root-find, with realisability warnings when the target is infeasible, and no outer
optimizer, no surrogate, no training data. **This is the product's differentiator.** State
it explicitly in site copy and app onboarding — do not let the product read as "another
CST/NeuralFoil analysis tool."

### 3.4 Personas

| Persona | Need | Primary flow |
|---|---|---|
| Turbomachinery designer | Recover a blade section from a target loading/Mach distribution with manufacturable-constraint guarantees (LE radius, TE wedge, area) | `/api/presolve` → realisability check → `/api/inverse` → inspect constraints satisfied exactly (they're linear rows) |
| Aero educator | Demonstrate that inverse design need not be an optimization search; show students a determined root-find converge in real time | Draw a simple target Cp in the UI, watch streamed D-6 convergence |
| Researcher (reproducing/extending this work) | Verify the falsifiable test (T7) themselves; explore ablations | Site's gate-closure reports + downloadable manifests; app as a live demo of the same engine |

### 3.5 Functional and non-functional requirements

Numbered `FR-x` / `NFR-x`. Each flagged **Stage-1** (build now) or **Later** (post
Stage-1/Stage-2, explicitly deferred).

| ID | Requirement | Stage |
|---|---|---|
| FR-1 | Engine core (`src/cins/`) has zero I/O in `cst/`, `solver/` math paths; all file/network access isolated to adapters | Stage-1 |
| FR-2 | `POST /api/analyze` runs a direct mfoil solve and returns Cp, cl, cd | Stage-1 |
| FR-3 | `POST /api/fit` fits CST to supplied (x,y) coordinates, returns A, fit RMS, `cond(GᵀG)` | Stage-1 |
| FR-4 | `POST /api/presolve` returns the KKT linear pre-solve result and the realisability metric | Stage-1 |
| FR-5 | `POST /api/inverse` runs the monolithic Newton inverse and **streams** D-1 and D-6 diagnostics per iteration | Stage-1 |
| FR-6 | `POST /api/realisability` returns the realisability metric without a full inverse solve | Stage-1 |
| FR-7 | Frontend: draw or upload a target Cp curve | Stage-1 |
| FR-8 | Frontend: live convergence plot (streamed D-6) during an inverse run | Stage-1 |
| FR-9 | Frontend: display realisability warning when target is outside the CST-representable manifold (threshold from `presolve.realisability_threshold`) | Stage-1 |
| FR-10 | Auth via Supabase; saved designs scoped RLS owner-only | Stage-1 |
| FR-11 | Cascade (pitch/stagger/periodicity) inputs in UI | Later (Stage 2 dependent) |
| FR-12 | MISES-backed transonic solve option | Later (Stage 3 dependent) |
| FR-13 | Multi-user shared/collaborative design sessions | Later |
| FR-14 | Public gallery of saved designs (opt-in) | Later |
| NFR-1 | Engine core has no dependency on FastAPI/Next.js/Supabase — importable standalone for the paper's reproducibility artifacts | Stage-1 |
| NFR-2 | `/api/inverse` streaming must not block on a full Newton solve — per-iteration flush | Stage-1 |
| NFR-3 | Every run through the app that contributes to a saved design records the same manifest fields as `experiments/results/` (config hash, git SHA-equivalent app version, seed) for reproducibility | Stage-1 |
| NFR-4 | RLS policies verified by an explicit test (cross-user access denied) before any auth-gated endpoint ships | Stage-1 |
| NFR-5 | Site and app deploy independently; a broken app build must not block site updates | Stage-1 |
| NFR-6 | App scales to concurrent multi-user Newton solves without shared mutable state across requests (engine core is pure, so this should fall out of FR-1 — verify with a load test before declaring done) | Later |

## 4. Out of scope for this PRD

Cascade physics (dossier §8), MISES integration (dossier §9), and any monetization/business
model are not addressed here. If/when Stage 2 work begins, this PRD gets a Track A
addendum, not a rewrite.

## 5. Cross-references

- Task ladder and gate thresholds: [`docs/SPEC.md`](SPEC.md).
- Gate-closure contract (all three tracks close gates the same way): [`docs/GATES.md`](GATES.md).
- Statistical pre-registration backing the paper's evidence claims:
  [`docs/STATS_PROTOCOL.md`](STATS_PROTOCOL.md).
- Dossier: publication plan dossier §10, product/solver landscape dossier §6.
