# CINS — CST Inverse Newton Solver

Monolithic CST–Newton inverse airfoil design. Hypothesis: appending CST coefficients to
mfoil's global Newton system turns inverse design into a **square, determined root-find**
(no optimizer). Stage 1 = isolated airfoil on mfoil. See
[docs/CST_MISES_Monolithic_Inverse_Design.md](docs/CST_MISES_Monolithic_Inverse_Design.md)
(the research dossier — §7 is the executable spec) and [docs/SPEC.md](docs/SPEC.md).

## Three tracks, built together
1. **Science** — T0–T9 experiment ladder (dossier Appendix B), statistical benchmarking.
2. **Paper P1** — AIAA Journal/SciTech; `paper/` grows at every gate.
3. **Product** — GitHub Pages progress site (`site/`), full-stack app (`app/`, kundali
   pattern: deterministic engine → FastAPI → Next.js/Vercel → Supabase).

## Hard rules
- `vendor/mfoil/mfoil.py` is NEVER edited. All access via `src/cins/solver/mfoil_adapter.py`.
- **Config-driven:** no numeric parameter hardcoded in `src/`. Everything comes from
  `configs/*.yaml` validated by `src/cins/config.py` (pydantic). Gate thresholds live there too.
- **TDD:** failing test first. Gate tests in `tests/gates/` encode the dossier's numeric
  criteria and may NEVER be weakened without an ADR in `docs/adr/`.
- **Gate-closure contract** ([docs/GATES.md](docs/GATES.md)): a task gate closes only when
  tests green + domain (aero) validation met + adversarial review clean + diagnostics
  archived + docs/site/paper updated + merged & pushed. "Tests pass" alone closes nothing.
- Every experiment run writes an immutable manifest (config hash, git SHA, seed) under
  `experiments/results/`. Figures must be regenerable from manifests.
- Sign conventions and math notation: see `src/cins/CLAUDE.md`. Do not improvise.

## Workflow
- Branch per phase/task (`phase0-bootstrap`, `t2-cst-module`, …); merge to `main` + push
  to https://github.com/SharathSPhD/CINS.git at every gate closure.
- Adversarial review before every merge (multi-lens: correctness, numerics/conditioning,
  aero-domain, test adequacy). Findings archived in `docs/gates/`.
- Engineering contradictions go through the TRIZ engine; log to `docs/triz/`.
- Session handoffs → `.remember/remember.md`.
- Web tasks: use Claude-in-Chrome tools (user preference).

## Environment
Python venv at `.venv/` (`source .venv/bin/activate`); `pip install -e ".[dev]"`.
Run tests: `python -m pytest tests/ -q`. Lint: `ruff check src/ tests/`.
