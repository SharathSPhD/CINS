# P1 Results digest: T8 numbers for direct import

Source: `experiments/results/t8/ANALYSIS.md` (full analysis, deviations, caveats),
`benchmarks/REPORT.md` (executive summary). Figures: `experiments/results/t8/figures/`.
Every number below traces to a `result.json`/`diagnostics.json` file under
`experiments/results/t8/`; see ANALYSIS.md for the per-cell citation. **All values are
N=1 (single seed=42 run per cell). No confidence intervals are reported because none are
statistically defensible at N=1**; report as point values, per STATS_PROTOCOL's
Stage-1-lite scoping.

Caveat that applies to every subsection below, stated once here: T8 as executed is a
single-airfoil (NACA 2412) ablation matrix plus two extra single-airfoil cells (0012,
4415), **not** the pre-registered ~20-section NACA panel (`panel_naca.yaml` does not
exist in the repo). Do not present panel-level convergence-fraction language in P1 without
first running that panel.

**Superseded (2026-08-04, post-review):** the pre-registered NACA panel above has now
been run (`configs/experiments/panel_naca/*.yaml`, `experiments/results/t8/panel_*/`,
20 cells, seed=42); see `experiments/results/t8/ANALYSIS.md` "H1 addendum" and P1
§5.6 ("H1: NACA panel generalization"). Result: 18/18 generable sections recovered
(`err_free_inf` ≤ 1.5e-10, 3–7 iterations); 2 sections excluded (panel_0006: target
generation itself non-convergent; panel_44012: 44XXX mean line not implemented by the
vendor NACA5 generator). Wilson 95% LB at n=18 is 0.824, below the pre-registered ≥0.9
criterion for interval-arithmetic reasons (n>=35 required for LB>=0.9 at 100% success; n=29 reaches only 0.883 -- corrected 2026-08-06, the earlier n>=29 figure was wrong),
not a solver-performance shortfall. The single-airfoil-only caveat above still applies
to every other subsection of this digest (n-sweep, station-selection, flow-solve-count,
etc.), which remain NACA-2412-only, N=1 ablations. Only the H1 convergence claim itself
has been upgraded to panel-level evidence.

---

## §5.1 Self-consistent recovery (T7 falsifiable test / winning configuration)

- Configuration: NACA 2412, n=8/side, `le_treatment=prescribed`, `transition=forced`,
  `station_selection=qr_pivot`, `init=presolve`, `alpha_free=false` (`t8_n08_baseline`,
  identical to `experiments/run_t7.py`'s config).
- Recovery: `err_all_inf = 1.08e-11` in 4 Newton iterations (gate: < 1e-4, <= 9 iters;
  PASSES with large margin).
- Realisability (inviscid-consistent, ADR-0004 metric 1): 3.90e-4.
- Model gap (viscous vs. inviscid linearization, ADR-0004 metric 2, diagnostic not
  gating): 0.110.
- Station-selection submap conditioning: 90.3. **Do not quote this as the extended-system
  conditioning** (that is `cond_J ≈ 1.57e8` at this cell's first iteration, D-2): these
  are different matrices, ADR-0004.
- Figure: `figures/h3_convergence_overlay.png` (residual history overlay).

## §5.2 Ablations

### Station selection: identifiability (recommend leading with this finding)

| Selection | err_all_inf | Submap cond | Newton `converged` flag |
|---|---|---|---|
| `qr_pivot` (winning config) | **1.08e-11** | 90.3 | true |
| `even` (evenly-spaced) | **1.43e-3** (FAILS 1e-4 gate) | 3.47e12 | true |

Both cells' Newton loops report `converged: true`; only `qr_pivot` recovers the correct
design. This is the central methodological result of T8; see
`docs/triz/T7-identifiability.md` for the pre-T8 discovery this reproduces and sharpens.
Figure: `figures/station_selection.png`.

### Bernstein order n (FM-2 conditioning cliff)

| n | Iterations | err_all_inf | Submap cond | Extended-system cond_J (D-2, it. 0) | T2 Gram/fit cond (context) |
|---|---|---|---|---|---|
| 4 | 3 | 8.08e-12 | 10.6 | 6.46e7 | 498 |
| 6 | 4 | 1.59e-10 | 20.4 | 8.46e7 | 7,327 |
| 8 | 4 | 1.08e-11 | 90.3 | 1.57e8 | 108,538 |
| 10 | 4 | 1.46e-10 | 592 | 4.52e8 | 1,626,188 |
| 12 | **21** (FAILS 9-iter gate) | 6.31e-10 | 1,144 | 2.07e9 | 24,579,174 |

Cliff is between n=10 and n=12: iteration count is flat (3–4) through n=10, then jumps to
21. All three conditioning series are ADR-0004-distinct matrices (T2 fit/Gram, T7/T8
station submap, T6 D-2 extended system); plot and report separately, never conflate.
Figure: `figures/n_sweep.png`.

### Other single-factor ablations (all vs. `t8_n08_baseline`)

| Factor | Cell | Iterations | err_all_inf | Notes |
|---|---|---|---|---|
| Transition free vs forced | `t8_transition_free` | 4 | 1.28e-11 | no material difference |
| alpha free vs fixed | `t8_alpha_free` | 5 | 2.31e-9 | 1 extra iteration; consistent with camber-α null-direction documented pre-T8 |
| Init: perturbed vs presolve | `t8_init_perturbed` | 5 | 2.12e-11 | 43 vs 120 flow-solve-equiv (see H2 section); presolve buys efficiency, not correctness (§5.4) |
| LE treatment: none vs prescribed | `t8_le_none` | 4 | 6.50e-10 | submap cond roughly doubles (195.6 vs 90.3), still passes gate by 6 orders of magnitude |
| DOF over-determined (+1) | `t8_dof_over` | 0 (clean fail) | n/a | `"extended system not square: M+K=17 but n_A_free+n_alpha=16 (M=17, K=0, n_A_free=16)"` |
| DOF under-determined (−1) | `t8_dof_under` | 0 (clean fail) | n/a | `"extended system not square: M+K=15 but n_A_free+n_alpha=16 (M=15, K=0, n_A_free=16)"` |

### Airfoil generalization

| Airfoil | Iterations | err_all_inf | Submap cond | Model gap |
|---|---|---|---|---|
| 2412 (baseline) | 4 | 1.08e-11 | 90.3 | 0.110 |
| 0012 | 4 | 3.15e-11 | 83.9 | 0.083 |
| 4415 | 3 | 4.35e-11 | 117.9 | 0.163 |

N=1 each; encouraging but not a generalization claim (2 additional airfoils only).

## §5.3 Flow-solve count vs. nested optimization (H2)

**Corrected headline (do not use ≥100x; measured and rejected under two independent,
fair-paired controls):**

| Pairing (shared init strategy) | Monolithic `n_flow_solves_equivalent` | Nested LM `n_flow_solves_equivalent` | Ratio |
|---|---|---|---|
| Presolve-init | 120 | 373 | **3.1x** |
| Perturbed-init (cold-start) | 43 | 347 | **8.1x** |

Nested control: `scipy.optimize.least_squares(method="lm", ftol=xtol=gtol=1e-8, x_scale
="custom(|x0| floor 1e-3)")`, converged both times (`xtol` termination), 16 free
coefficients. This is a competent modern LM solver, not a weak baseline. The
pre-registered ≥100x threshold likely encodes an older class of nested-optimization
baseline (e.g. surrogate/Kriging-in-the-loop) than what was actually run; report this
attribution explicitly in the Discussion (see `benchmarks/REPORT.md`).

Recommended P1 sentence: *"The monolithic architecture requires 3.1–8.1x fewer
flow-residual evaluations than a fairly-paired, well-tuned nested Levenberg-Marquardt
baseline (scipy.least_squares), depending on initialization strategy, substantially less
than the order-of-magnitude reduction hypothesized a priori, though the qualitative
advantages of determinism, guaranteed local quadratic convergence, and exact analytic
constraint-row Jacobians persist independent of this ratio."*

Figure: `figures/h2_flow_solves.png` (linear, non-truncated axis; both fair-paired
comparisons; pre-registered 100x line shown for scale).

## §5.4 Presolve vs. station-selection as the uniqueness guard

- `t8_init_perturbed` (no presolve, `station_selection=qr_pivot`): 43 flow-solve-equiv, 5
  iterations, err 2.12e-11, submap cond 89.8 (essentially identical to baseline's 90.3,
  since station selection depends on the stations, not the initial guess).
- `t8_n08_baseline` (presolve, same station selection): 120 flow-solve-equiv, 4
  iterations, err 1.08e-11, submap cond 90.3.
- Interpretation: skipping presolve costs ~1 extra Newton iteration but *reduces* total
  flow-solve count (43 < 120) and does not cost correctness. Presolve consumes roughly 77
  flow-solve-equivalents (~64% of the baseline total), primarily for iteration efficiency
  and starting-residual quality, not for the uniqueness guarantee, which comes from
  `station_selection=qr_pivot` alone. Not verified in the sharper crossed form
  (`init=perturbed` x `station_selection=even`); flag as future work, not as tested.

## §5.5 Quadratic convergence tail (H3)

Method: STATS_PROTOCOL's 3-point local order estimator, applied only where >= 3 residual
values exist strictly above the ~1e-9 FD-noise floor (excludes floor-polluted points; the
raw `convergence_order` field in each `result.json` does *not* apply this exclusion and
should not be quoted directly).

| Cell | Recomputed order (clean tail) |
|---|---|
| t8_alpha_free | 1.09 |
| t8_init_perturbed | 2.08 |
| t8_n06 | 2.46 |
| t8_transition_free | 2.15 |
| t8_n12 | 4.24 (late-tail 3-point estimate; read as "clearly superlinear," not literal quartic order) |

**Median order: 2.15 (n=5 estimable cells), meets the pre-registered >= 1.8 target.**
The remaining 7/12 converged cells cannot be scored by this method because they reach the
solver's residual floor in only 2 post-initial steps, too fast for a 3-point estimator to
have 3 clean points. This is itself consistent with (though it does not formally confirm)
fast superlinear-to-quadratic convergence.

Figure: `figures/h3_convergence_overlay.png`.

## Suggested abstract-level correction

`paper/p1_main.tex`'s current abstract placeholder note reads: *"Headline: two to three
orders of magnitude fewer flow solves plus determinism and uniqueness."* Based on T8:
replace the flow-solve magnitude claim with **"3–8x fewer flow-solve-equivalents than a
fairly-paired, competently-tuned nested baseline"** and keep "determinism and uniqueness."
The uniqueness claim is in fact *better* supported by T8 than before, via the
station-selection identifiability finding (§5.2), even though the flow-solve magnitude
claim needed correcting downward.
