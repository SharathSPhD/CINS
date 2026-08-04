# CINS — CST Inverse Newton Solver

**Inverse airfoil design without an optimizer.** Give CINS a target pressure
distribution; it returns the airfoil — as the solution of a single square Newton
root-find, not an optimization search.

## The idea in one paragraph

Classical inverse design wraps a flow solver in an optimization loop: guess a shape,
solve the flow, measure the mismatch, repeat hundreds of times. CINS instead
parameterizes the airfoil with the Class-Shape Transformation (CST), whose surface is
**linear** in its coefficients. That linearity lets the geometric unknowns be appended
directly to the flow solver's global Newton system — flow state and shape converge
*together*, quadratically, in ~5–15 iterations. Geometric constraints (leading-edge
radius, trailing-edge wedge, cross-sectional area) become exact linear rows, not
penalty terms. Constrained shape optimization becomes constrained root-finding.

## Status — Stage 1 (isolated airfoil, mfoil)

| Gate | Description | Status |
|------|-------------|--------|
| T0 | Environment + mfoil baseline solve | **closed** |
| T1 | mfoil internals introspection | **closed** |
| T2 | CST module (fit RMS < 0.1% chord) | **closed** |
| T3 | Constraint rows (area to 1e-10) | **closed** |
| T4 | Analytic pre-solve + realisability | **closed** |
| T5 | Extended Newton system | **closed** |
| T6 | Diagnostics D1–D6 | **closed** |
| T7 | **Falsifiable test: recover A\* from its own Cp** | **PASSED — A\* recovered to 1.1e-11 in 4 iterations** |
| T8 | Ablations + statistical benchmark | **closed** (H1 panel deferred) |
| T9 | Stage 2 (cascade) design review | in progress |

Full research dossier: [docs/CST_MISES_Monolithic_Inverse_Design.md](docs/CST_MISES_Monolithic_Inverse_Design.md)

## Repository layout

- `src/cins/` — the Python package (CST math, constraints, pre-solve, extended Newton solver, diagnostics, benchmarks)
- `vendor/mfoil/` — Fidkowski's mfoil (MIT, unmodified; see PROVENANCE.md)
- `configs/` — all run parameters as validated YAML (config-driven, nothing hardcoded)
- `tests/` — unit / gates / regression (TDD; gate tests encode the dossier's numeric criteria)
- `experiments/results/` — git-versioned run manifests + results (reproducible figures)
- `docs/` — SPEC, PRD, GATES contract, ADRs, TRIZ logs, gate-closure reports
- `paper/` — AIAA paper P1, grown at every gate
- `site/` — GitHub Pages progress dashboard
- `app/` — full-stack app (FastAPI + Next.js + Supabase), ships after gate T7

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -q
```

## License

MIT (CINS code). Vendored mfoil is MIT © Krzysztof J. Fidkowski.
