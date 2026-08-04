# GATES — Gate-Closure Contract

Status: binding. This document is the *only* definition of what "done" means for a task
gate (T0–T9) in CINS. It is referenced by [`CLAUDE.md`](../CLAUDE.md),
[`docs/SPEC.md`](SPEC.md) (per-task numeric thresholds), and
[`tests/CLAUDE.md`](../tests/CLAUDE.md) (gate-test policy).

**"Tests pass" closes nothing.** A gate closes only when all six conditions below hold,
in full, with evidence archived. This applies equally to a human closing a gate and to any
autonomous loop (e.g. a `ralph-loop`-style agent) driving the T0–T9 ladder — such a loop
MUST terminate iteration on this contract, never on green CI alone. If an autonomous loop
believes a gate is closed, it still produces the report in §3 and stops for review before
proceeding to the next task, unless a human has explicitly pre-authorized unattended
progression past a specific gate.

## 1. The six conditions

A gate ID (T0…T9) closes only when **all** of the following are true simultaneously:

### (1) Unit + gate tests green in CI
- `python -m pytest tests/ -q` passes, including the gate's specific tests in
  `tests/gates/`.
- Gate tests assert against `configs/default.yaml gates:` values, not hardcoded numbers
  (`tests/CLAUDE.md`).
- No test was skipped, weakened, or removed to reach green. Any such change requires a
  prior ADR in `docs/adr/` — its absence blocks closure outright.

### (2) Domain (aero) validation — the dossier's quantitative criterion, met and archived
The criterion is task-specific, defined in `docs/SPEC.md` §7 and sourced from
`configs/default.yaml gates:`. Non-exhaustive examples, restated here because they are the
substance of what "domain validation" means (do not treat this as the full list — `SPEC.md`
§7 is authoritative):

| Task | Domain criterion | Threshold source |
|---|---|---|
| T0 | NACA 2412 α=2°, Re=1e6 viscous solve converges, cl in sanity band | `gates.t0_cl_range` |
| T2 | CST fit RMS on NACA 2412 and sCO2 baseline < threshold; `cond(GᵀG)` vs n curve archived as a figure/table | `gates.t2_fit_rms_max` |
| T3 | `area_row` closed-form value vs numerical quadrature agrees to tolerance | `gates.t3_area_quadrature_tol` |
| T4 | Realisability metric computed and thresholded on at least one known-realisable and one deliberately-unrealisable target | `presolve.realisability_threshold` |
| T5 | `M + K = n_A + 1` assertion exercised (positive and at least one deliberately-violating case caught) | derived, dossier §7.6 |
| T6 | D-1..D-6 each produce a non-trivial artifact on a real run (not a stub/mock) | — |
| T7 | `‖A − A*‖∞ < threshold` in ≤ max iterations, quadratic tail visible in D-6, for both NACA 2412 and sCO2 baseline | `gates.t7_a_recovery_inf_norm`, `gates.t7_max_newton_iters` |
| T8 | Ablation matrix (dossier §7.9) run in full; statistical protocol in `docs/STATS_PROTOCOL.md` satisfied (H1–H3 evaluated, not just computed) | `docs/STATS_PROTOCOL.md` |
| T9 | Stage 2 design review document exists and addresses the checklist in dossier §8 | — |

Passing this condition means: the number was *measured on a real run*, not asserted by a
test with mocked internals, and the run artifact exists (see condition 4).

### (3) Adversarial review, zero unresolved CONFIRMED findings
- Multi-lens review before merge: correctness, numerics/conditioning, aero-domain
  plausibility, test adequacy (per `CLAUDE.md` Workflow section).
- Findings are triaged as `CONFIRMED` (real issue, must resolve or explicitly waive with
  rationale) or `NOT-CONFIRMED` (reviewed, judged not applicable, rationale recorded).
- **Zero unresolved CONFIRMED findings** at merge time. A CONFIRMED finding may be
  resolved by fixing it, or — rarely — by a written waiver signed off in the report
  (§3), never by silent dismissal.
- Archived under `docs/gates/<task-id>-review.md` (or `docs/gates/<task-id>/` if multiple
  review passes are needed).

### (4) Diagnostics artifacts archived with a run manifest
- Every experiment run that produced the evidence for (2) writes an **immutable manifest**
  under `experiments/results/` recording: config hash (hash of the resolved
  `configs/*.yaml` used), git SHA, seed (`experiment.seed`, default 42), and enough metadata
  to regenerate the run.
- Figures/tables referenced in (2) or in the paper/site must be regenerable from the
  manifest — no hand-edited numbers.
- D-1..D-6 diagnostic outputs relevant to the task are included in the archive, not just
  summary statistics.

### (5) Docs + site + paper updated
- `docs/SPEC.md` cross-references remain accurate (update if the task changed an equation,
  a config key, or a threshold — with an ADR if it's a threshold).
- `site/` (GitHub Pages progress site) reflects the task as done, with a link to the
  archived diagnostics.
- `paper/` grows at every gate per `CLAUDE.md` — at minimum the relevant section/figure
  placeholder is populated or updated, per the P1 novelty framing in `docs/PRD.md`.

### (6) Branch merged to main and pushed
- Task branch (e.g. `t2-cst-module`) merged to `main`.
- Pushed to `https://github.com/SharathSPhD/CINS.git`.
- No gate is closed while work sits only on a local branch.

## 2. Ordering and dependency

Conditions are not strictly sequential, but in practice: (1) unlocks (2) (you need green
tests to trust a domain-validation run); (2)+(1) together are the input to (3); (3) clean is
a precondition to (6); (4) can be produced in parallel with (2)–(3) but must be archived
before (6); (5) is typically the last step before (6). Do not merge (6) before (3) is clean.

## 3. Gate-closure report template

Every closed gate produces a markdown report at `docs/gates/<task-id>-closure.md`. Use this
template verbatim (delete guidance text in brackets):

```markdown
# Gate Closure Report — <Task ID> (<short title>)

**Date:** <YYYY-MM-DD>
**Branch:** <branch-name>  →  merged to main at <commit-sha>
**Reported by:** <name / agent>

## 1. Gate ID and scope
<One paragraph: what this task delivered, per docs/SPEC.md §7.>

## 2. Evidence table

| Condition | Status | Evidence |
|---|---|---|
| (1) Tests green | ✅/❌ | CI run link / `pytest` output summary |
| (2) Domain validation | ✅/❌ | Measured value vs threshold (from configs/default.yaml gates:); manifest path |
| (3) Adversarial review | ✅/❌ | Link to docs/gates/<task-id>-review.md |
| (4) Diagnostics archived | ✅/❌ | experiments/results/<run-id>/ manifest path |
| (5) Docs/site/paper updated | ✅/❌ | Links to changed files |
| (6) Merged & pushed | ✅/❌ | Commit SHA, PR link |

## 3. Domain criterion detail
<The specific number(s) from docs/SPEC.md §7 gate table, measured value, pass/fail, and
the config key(s) that define the threshold.>

## 4. Review findings and resolutions

| Finding | Lens | Status (CONFIRMED/NOT-CONFIRMED) | Resolution |
|---|---|---|---|
| <finding> | correctness/numerics/aero-domain/test-adequacy | | fixed in <commit> / waived because <reason> |

## 5. Artifacts list
- experiments/results/<run-id>/manifest.json (config hash, git SHA, seed)
- <figures, tables, D-1..D-6 outputs referenced>

## 6. Sign-off
- [ ] All six conditions in docs/GATES.md §1 met
- [ ] No unresolved CONFIRMED findings
- Signed off by: <name/agent>, <date>
```

## 4. Regression protection

Once a gate closes, its measured numbers are pinned as a regression test in
`tests/regression/` (per `tests/CLAUDE.md`). Later work that silently degrades a closed
gate's numbers is a test failure, not a documentation update.

## 5. Cross-references

- Numeric thresholds: [`docs/SPEC.md`](SPEC.md) §7, sourced from
  [`configs/default.yaml`](../configs/default.yaml) `gates:`.
- Dossier task definitions: [`docs/CST_MISES_Monolithic_Inverse_Design.md`](CST_MISES_Monolithic_Inverse_Design.md)
  §7, Appendix B.
- Statistical pre-registration for T8: [`docs/STATS_PROTOCOL.md`](STATS_PROTOCOL.md).
- Product/paper scope gated at each closure: [`docs/PRD.md`](PRD.md).
- Test policy: [`tests/CLAUDE.md`](../tests/CLAUDE.md).
