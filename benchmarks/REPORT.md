# T8 Benchmark Report — Executive Summary

**Source data:** `experiments/results/t8/*/result.json`, `diagnostics.json`. Full
per-hypothesis analysis: `experiments/results/t8/ANALYSIS.md`. Figures:
`experiments/results/t8/figures/*.png` (regenerate with
`.venv/bin/python -m cins.benchmarks.figures`). Pre-registered protocol:
`docs/STATS_PROTOCOL.md`. Reporting rules: `docs/adr/ADR-0004.md`.

This report is written for P1's Results/Discussion sections and for anyone deciding
whether T8's evidence is strong enough to ship. It leads with what T8 does **not**
establish, because that scoping determines how every number below should be read.

---

## What T8 establishes

- **A working, deterministic monolithic CST–Newton inverse solve** on NACA 2412 (baseline)
  and two generalization airfoils (0012, 4415), passing the T7 dual-criterion gate
  (`err_all_inf < 1e-4` and `iterations <= 9`) in 10 of 12 legitimately-comparable
  ablation cells.
- **A concrete, quantified identifiability mechanism.** QR-pivoted station selection
  (`station_selection=qr_pivot`) is not a minor tuning knob — it is the difference between
  recovering the true design (err 1.08e-11, submap cond 90) and converging cleanly to a
  *wrong* root that also zeros the Newton residual (err 1.4e-3, submap cond 3.5e12,
  `t8_station_even`). Both cells report the solver's internal `converged: true`; only one
  is actually correct. This is the single most important, most defensible finding in T8
  — see "Central methodological result" below.
- **A genuine, if modest, flow-solve reduction vs. a competently-tuned nested baseline**:
  roughly 3–8x fewer flow-solve-equivalents, fair-paired by shared initialization
  strategy, verified against two independent nested-LM controls (warm-started and
  cold-start).
- **A real conditioning cliff (FM-2)** between Bernstein order n=10 and n=12: Newton
  iterations are flat at 3–4 through n=10, then jump to 21 at n=12, tracking (but not
  identical to) three independently-measured, ADR-0004-distinct conditioning quantities
  that all grow with n.
- **Locally superlinear-to-quadratic Newton convergence** where it can be measured: median
  recomputed order 2.15 across the 5 (of 12) cells with enough clean pre-floor iterations
  for the pre-registered 3-point estimator to apply; the other 7 cells converge too fast
  (3–4 total iterations) to be measured by that method at all, which is itself a
  favorable — if statistically silent — signal.
- **Clean, actionable failure modes for deliberate DOF mis-squaring (FM-1)**: both the
  over- and under-determined ablation cells fail at construction time with an explicit,
  correct error string, zero Newton iterations spent, no silent wrong answer.

## What T8 does NOT establish

- **No panel evaluation exists.** STATS_PROTOCOL pre-registers H1 as a Wilson-CI
  converged-fraction claim over a ~20-section NACA panel (`configs/experiments/panel_naca
  .yaml`) plus a ~100-section stratified UIUC panel. Neither config file nor any panel run
  exists in this repository. T8 as executed is a single-airfoil (NACA 2412) ablation
  matrix plus two extra single-airfoil spot-checks (0012, 4415). **This is Stage-1-lite
  evidence, not the pre-registered panel evidence** — the panel run is the natural next
  step before any airfoil-generality claim goes into P1's Results with confidence
  language attached.
- **Single seed, single run per cell (N=1).** No bootstrap CIs, no Wilcoxon tests are
  computed anywhere in this report, because none of STATS_PROTOCOL's inferential
  machinery applies to N=1 samples. Every number below is a point value.
- **Subcritical, single operating condition.** All cells share one `operating.*` block
  (`configs/default.yaml`) — one Re, one alpha, one Mach regime (subcritical, presumably;
  not swept). No claim here generalizes across flow regimes.
- **Single airfoil *family* (NACA 4-digit) plus two additional NACA sections** — no UIUC
  or turbine-proxy (VKI LS89, T106) sections were run; per STATS_PROTOCOL §3.2 those are
  conditional on licensed coordinate data, which has not been acquired.
- **The ≥100x H2 headline claim does not survive contact with a competent nested
  baseline** — see below, this is the most consequential correction in this report.

## The honest H2 story

The pre-registered claim (STATS_PROTOCOL H2): monolithic uses **≥100x** fewer
flow-residual evaluations than a tuned nested `scipy.least_squares` baseline.

**Measured, fair-paired result: REJECTED.** Two independent controls, each matched to a
monolithic run sharing the same initialization strategy (STATS_PROTOCOL's fair-pairing
requirement):

| Pairing | Monolithic | Nested LM control | Ratio |
|---|---|---|---|
| Presolve-init (both warm-started from T4 pre-solve) | 120 solves | 373 solves | **3.1x** |
| Perturbed-init (both cold-started, no presolve) | 43 solves | 347 solves | **8.1x** |

Neither ratio is within an order of magnitude of ≥100x, let alone two-to-three orders of
magnitude. This report states that plainly rather than reframing the number.

**Why the ratio landed at 3–8x, not ≥100x — this is a finding, not just a shortfall.**
The nested control is `scipy.optimize.least_squares(method="lm")` with tight tolerances
(`ftol=xtol=gtol=1e-8`) and properly scaled parameters (`x_scale` from `|x0|`, floored at
1e-3), over 16 well-conditioned free coefficients. It converges the cold-start case in
`n_nfev=6` outer LM iterations. **A modern Levenberg-Marquardt solver with a
finite-difference Jacobian over ~16 well-scaled parameters is a genuinely strong
comparator** — nothing like the Dakota-surrogate/Kriging-in-the-loop nested-optimization
baselines that a ≥100x figure of that magnitude typically describes in the older
aerodynamic-shape-optimization literature the dossier's framing appears to draw on. **The
pre-registered ≥100x threshold plausibly encodes an outdated class of baseline; measuring
against a strong modern one and getting 3–8x is a more informative, more honest result
than either confirming or badly missing the original number would have been.**

**What survives the correction, and belongs in P1's Discussion, are the qualitative
differentiators** — determinism (the monolithic solve has no stochastic restart or
local-optima risk; the nested LM control, being local, shares this property under a
convex-enough basin but the monolithic architecture has a stronger structural argument via
the identifiability finding below), the demonstrated quadratic-tail convergence (§3, ANALYSIS.md),
the exact/analytic linear-constraint-row Jacobian block (no FD noise anywhere in the
constraint rows, unlike a fully-FD nested Jacobian), and the D-1 through D-6 per-iteration
diagnostics the nested method has no equivalent instrumentation for. These are
architectural properties, not a flow-solve ratio, and they do not require ≥100x to be
worth reporting — but they should not be allowed to quietly stand in for the numeric claim
either. P1 should state the corrected 3–8x ratio explicitly and separately from these
qualitative points.

## The identifiability finding — the central methodological result

This is the finding this report recommends leading with in P1, ahead of the flow-solve
ratio: **station selection, not initialization, is what makes the square extended-Newton
system have a unique, correct solution.**

- Evenly-spaced target stations (`t8_station_even`) produce a station-sensitivity submap
  with condition number ~3.5e12. The Newton loop still reports `converged: true` (its
  residual does go to the solver's floor) — but it converges to a coefficient vector 1.4e-3
  away (∞-norm) from the true design, 14x over the H1 gate threshold. "Converged" and
  "correct" are different claims here, and the difference is invisible unless you check
  `err_all_inf` against the true coefficients, not just the residual norm.
- QR-pivoted station selection (`station_selection=qr_pivot`, the winning configuration)
  reduces that same submap's condition number to ~90 and recovers the true design to
  3.15e-11 to 1.08e-11 across every cell it's used in (10/10 qr_pivot cells that reach the
  Newton loop pass the accuracy gate).
- Skipping the T4 pre-solve's initial-guess contribution entirely (`t8_init_perturbed`,
  `init=perturbed`, still using `station_selection=qr_pivot`) still converges to the
  correct root (2.12e-11) using *fewer* total flow solves (43) than the presolve baseline
  (120) — at the cost of one extra Newton iteration. This decomposition (§5,
  ANALYSIS.md) implies presolve is doing efficiency work (fewer Newton iterations, cheaper
  starting residual), not correctness work — the correctness guarantee comes from which
  stations are chosen, not from how well the initial guess is seeded. This has not been
  tested in the sharper 2x2 form (`init=perturbed` crossed with `station_selection=even`)
  and is flagged as the natural next ablation, not claimed as directly verified.

This finding directly extends `docs/triz/T7-identifiability.md`'s pre-T8 discovery (the
same phenomenon, cond ~1e7, error 1.4e-3–6e-2) with a controlled T8 ablation cell that
reproduces and quantifies it cleanly, plus a companion ablation (n-sweep, FM-2) showing
the same submap conditioning mechanism degrades gracefully with Bernstein order until a
sharp cliff at n=12.

## Recommendations for P1

1. Report H2 as **~3–8x** (both fair-paired ratios, not a single number), not ≥100x;
   attribute the gap partly to the nested baseline being a strong modern LM solver, not a
   weak strawman — this reframing is itself worth a sentence in the Discussion.
2. Lead the Results section's ablations discussion with the identifiability finding
   (station selection), not the flow-solve ratio — it is the more novel, more defensible,
   more precisely quantified contribution, and is explicitly flagged in
   `docs/triz/T7-identifiability.md` as a candidate methodological contribution beyond the
   original dossier.
3. Report H1 as a Stage-1-lite result (10/12 ablation cells pass the dual-criterion gate,
   3 airfoils total) with an explicit statement that the pre-registered NACA/UIUC panel
   evaluation has not yet been run, rather than reporting a converged-fraction number that
   implies panel-level evidence.
4. Report H3's median order (2.15, n=5 estimable cells) with the explicit caveat that most
   converged cells were too fast (3–4 iterations) for the pre-registered 3-point estimator
   to apply — this is favorable evidence read qualitatively, not a weak result.
5. Before final submission, run the pre-registered NACA panel (`panel_naca.yaml` needs to
   be written per STATS_PROTOCOL §3.1's frozen list) to get an actual Wilson-CI H1 result;
   this is the largest remaining gap between what P1 can currently claim and what
   STATS_PROTOCOL pre-registered.
