# STATS_PROTOCOL — Pre-Registered Statistical Protocol for T8/T9

Status: binding, **pre-registered before T8 runs execute**. This document is written before
any ablation or benchmark data exists. Changing a hypothesis, threshold, or test after
seeing results is a protocol violation — if a change is genuinely warranted, it goes through
an ADR in `docs/adr/` documenting what was seen and why the change is justified, exactly
like a gate-threshold change (`tests/CLAUDE.md`).

Cross-references: task/gate definitions in [`docs/SPEC.md`](SPEC.md) §7 (T7 falsifiable
test, T8 ablations), gate-closure contract in [`docs/GATES.md`](GATES.md), paper evidence
requirements in [`docs/PRD.md`](PRD.md) Track B, dossier §7.8–§7.9.

## 1. Fixed experimental parameters

- **Seed:** `experiment.seed = 42` (`configs/default.yaml`). Every stochastic step (random
  initialisation ablation, bootstrap resampling) is seeded from this value or a documented
  deterministic derivation of it (e.g. `seed + airfoil_index`) — never from wall-clock time.
- **Regenerability:** every figure in the paper or site must be producible by
  `python -m cins.benchmarks run configs/experiments/<cell>.yaml`. A figure with no
  corresponding config cell is not permitted in P1 or the site.
- **Manifest:** every run writes config hash, git SHA, seed to `experiments/results/`
  (`docs/GATES.md` condition 4).

## 2. Hypotheses

### H1 — Monolithic convergence on realisable targets

**Statement:** The monolithic CST-Newton inverse converges on self-generated (guaranteed
realisable, per the T7 falsifiable-test construction, dossier §7.8) targets across the
airfoil panel (§4).

**Success metric:** converged fraction of the panel, with a **95% Wilson score interval**
(preferred over normal-approximation CI for a proportion, especially near 0 or 1).
Convergence criterion per airfoil = the T7 gate criterion: `‖A − A*‖∞ < gates.t7_a_recovery_inf_norm`
within `gates.t7_max_newton_iters` iterations with a quadratic tail in D-6.

**Target:** converged fraction ≥ 0.9 on the NACA panel (lower bound of the Wilson interval
reported alongside the point estimate; the ≥0.9 target applies to the point estimate, the
interval is reported for honesty about panel-size uncertainty).

### H2 — ≥100× fewer flow-residual evaluations than a tuned nested baseline

**Statement:** The monolithic solve requires at least 100× fewer flow-residual evaluations
than a tuned `scipy.least_squares` nested baseline (dossier §7.9 last ablation row) to reach
the same target-Cp match quality, per airfoil.

**Design:** paired — same airfoil, same target Cp, monolithic vs nested baseline, produces
one ratio `evals_nested / evals_monolithic` per airfoil. Ratios are the unit of analysis.

**Baseline tuning requirement:** the nested `scipy.least_squares` baseline must be
genuinely tuned (reasonable tolerances, a competent initial guess — e.g. the same T4
pre-solve given to the monolithic method, not a strawman) before comparison; an untuned
baseline invalidates H2 regardless of the numeric outcome. Document the baseline's
`scipy.least_squares` call signature (method, `x_scale`, `ftol`/`xtol`/`gtol`, max
iterations) in the run manifest.

**Test:** Wilcoxon signed-rank test on the per-airfoil ratios (or on `log(ratio)` — report
which), **one-sided** (alternative: monolithic uses fewer evaluations), since H2 is
directional by construction.

**Effect size / CI:** bootstrap BCa (bias-corrected and accelerated) 95% confidence interval
on the **median** ratio, resampling airfoils (paired resampling — keep monolithic/nested
pairs together). Report the median ratio, its BCa CI, and the Wilcoxon p-value together;
the ≥100× claim is judged against the median ratio and its CI lower bound, not the p-value
alone (a significant-but-small ratio does not support the claim).

### H3 — Quadratic convergence tail

**Statement:** Newton convergence (D-6: log‖R‖ vs iteration) shows a quadratic tail near the
root, confirming the architectural claim that CST's exact/constant geometric Jacobian block
preserves Newton's quadratic local convergence.

**Method:** for each converged run, fit the local convergence order p from the final 3
iterations' residual norms via
`p ≈ log(‖R_k‖ / ‖R_{k-1}‖) / log(‖R_{k-1}‖ / ‖R_{k-2}‖)`
(standard discrete convergence-order estimator; requires at least 3 residual-norm points
strictly before the iteration hits `newton.rtol` and stalls at machine precision — exclude
iterations where ‖R‖ is already at the solver's floor, since the ratio is meaningless there).

**Reported quantity:** the distribution of estimated order p across all converged panel
airfoils (median, IQR, histogram/D-6 overlay figure).

**Target:** median estimated order ≥ 1.8 (quadratic = 2; ≥1.8 allows for the known
degradation from the C⁰ transition closure, FM-4, and finite-precision effects near
convergence, while still being clearly super-linear).

## 3. Panel definition

The evaluation panel is stratified and must be enumerated in the run manifest, not
regenerated ad hoc per run.

### 3.1 NACA 4/5-digit family (≈20 sections, enumerated)

4-digit (camber/thickness spread):
`0006, 0009, 0012, 0015, 0018, 2412, 2415, 4412, 4415, 6412, 2408, 4408, 0021, 0025, 6409`

5-digit (representative cambered, moderate/high-lift):
`23012, 23015, 23018, 24012, 44012`

(≈20 total; exact list is frozen at the time `configs/experiments/panel_naca.yaml` is
written and copied into that config file — this list is the pre-registration commitment,
the config file is the executable copy.)

### 3.2 Turbine proxies (conditional)

`VKI LS89`, `T106` — **included only when coordinate data has been acquired and licensed
for use.** If coordinates are not obtained before T8 execution, these are excluded from the
panel and the exclusion is reported explicitly in the T8 closure report (`docs/GATES.md`
§3) — not silently dropped.

### 3.3 UIUC sections (~100, stratified)

~100 sections drawn from the UIUC Airfoil Coordinates Database, **stratified by thickness
decile and camber decile** (10×10 strata, approximately uniform sampling within reachable
strata; some corner strata — e.g. very high camber + very high thickness — may be sparsely
populated in the real UIUC set, in which case take all available sections in that stratum
rather than upsampling). The exact selection (which UIUC files, by name, and their
thickness/camber decile assignment) is written to
`configs/experiments/panel_uiuc.yaml` and is itself part of the manifest for any run that
uses this panel.

## 4. Ablation matrix

Exactly per dossier §7.9 — reproduced here for completeness, not modified:

| Ablation | Levels | Tests |
|---|---|---|
| Bernstein order n | 4, 6, 8, 10, 12, 16 per side | FM-2 — find the conditioning cliff |
| LE treatment | none / Kulfan LEM / Masters unwrapped / prescribed first 5% chord | FM-3 — expect prescribed-LE most robust |
| Transition | forced trip / free | FM-4 |
| DOF accounting | `M + K = n_A + 1` (correct) vs deliberately over-determined vs deliberately under-determined | FM-1 — confirm D-2 catches the deliberately-wrong cases |
| Initialisation | T4 pre-solve vs baseline-airfoil guess vs random | Validates T4 pre-solve necessity |
| Control (baseline) | monolithic vs `scipy.least_squares` nested over mfoil calls | H2's paired comparison |

Each ablation cell is one `configs/experiments/<cell>.yaml`, run against the full panel
(§3) unless a cell is explicitly scoped smaller (e.g. the DOF-accounting ablation's
deliberately-wrong cases only need to demonstrate D-2 catches them, not a full panel sweep
— state the scoping in the cell's config comments).

## 5. Multiple-comparison handling

The ablation matrix runs many hypothesis tests (e.g. per-n conditioning comparisons, per-LE-
treatment success-rate comparisons). Wherever an ablation dimension produces more than one
pairwise test against a reference level (e.g. each n compared to n=8 baseline, each LE
treatment compared to "none"), apply **Holm-Bonferroni** step-down correction across that
family of tests before reporting significance. Family boundaries:

- All pairwise n-vs-reference conditioning tests = one family.
- All pairwise LE-treatment-vs-"none" convergence-rate tests = one family.
- All pairwise transition-mode tests = one family.
- H1, H2, H3 (the three headline hypotheses) are **not** corrected against each other — they
  are pre-registered as independent primary claims, not a multiple-testing family; each
  stands or falls on its own stated threshold.

Report both raw and Holm-Bonferroni-adjusted p-values in ablation tables.

## 6. Exclusion rules

**mfoil direct-solve non-convergence excludes the airfoil from the panel for that run cell,
and is reported, not silently dropped.** Specifically:

- If mfoil's direct (forward) solve fails to converge on a panel airfoil under the fixed
  `operating.*` conditions (`configs/default.yaml`), that airfoil is excluded from all
  downstream inverse-design statistics for that experiment cell (H1/H2/H3 computed on the
  reduced panel).
- The exclusion count and the excluded airfoil identifiers are recorded in the run manifest
  and surfaced in the T8 closure report's evidence table (`docs/GATES.md` §3).
- An exclusion rate above 10% of the panel for a given cell is itself a reportable finding
  (may indicate the operating condition, not the inverse method, is the limiting factor) and
  must be called out in the paper's limitations discussion, not buried in a footnote.
- Exclusions are determined once per panel/operating-condition combination and reused
  across ablation cells that share that combination, rather than re-litigated per cell —
  this keeps the panel comparable across the ablation matrix.

## 7. What "regenerable" means in practice

For every figure or table appearing in `paper/` or `site/`:
1. There exists a `configs/experiments/<cell>.yaml`.
2. `python -m cins.benchmarks run configs/experiments/<cell>.yaml` reproduces the
   underlying data (writing to `experiments/results/`) using only `experiment.seed`.
3. The figure/table generation script reads only from that run's manifest and output —
   no manual number entry.

A figure that cannot be traced this way does not ship, regardless of how it was actually
produced during exploratory work.
