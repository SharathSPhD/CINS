# Gate closure report — T4, T5, T6, T7 (consolidated)

**Closed:** 2026-08-04 · **Re-run under the current station addressing:**
2026-08-06 · **Evidence:** experiments/results/t7_naca2412/{result.json,
run.log, diagnostics.json}

## T7 — the falsifiable test (dossier §7.8): PASS

Target stations were originally addressed by panel-node index. On 2026-08-05
that changed to (surface, x/c) with interpolation, because a node index stops
denoting the same physical location once the geometry moves. T7 was re-run
under the new addressing; both sets pass every criterion with several orders
of margin, and the numbers below are the current ones. Anything quoting
1.079e-11 in 4 iterations is the earlier addressing.

| Criterion | Threshold | Measured (current) | Measured (node-index) |
|---|---|---|---|
| ‖A−A*‖∞ over the 16 FREE coefficients | < 1e-4 | **2.747e-11** | 1.079e-11 |
| Newton iterations | ≤ 9 | **6** | 4 |
| Quadratic tail (D-6) | visible | 5.85e-4 → 1.57e-7 → 9.47e-12 | 5.9e-4 → 3.1e-6 → 1.0e-10 |
| Release-and-verify Δcl | < 1e-3 | **3.39e-12** | 8.0e-13 |
| Release-and-verify Δcd | < 2e-4 | **3.02e-14** | 1.1e-14 |

Submap cond 90.26, realisability 3.896e-4 (inviscid-consistent, ADR-0004),
model gap 0.110. Summary archived to result.json with a manifest; previously
these existed only in console output.

Framing per review: 16 coefficients recovered by Newton; A_u0/A_l0 prescribed
(le_treatment=prescribed) — pinned by design, not recovered.

## Adversarial review (6 attack vectors) — all findings resolved
1. **Circularity** — refuted by the reviewer (perturbation material, no aliasing).
2. **Station-index correspondence** (PLAUSIBLE, implementation-dependent) → originally
   answered with an explicit guard: max |dx/c| at stations = 6.1e-6, asserted < 2e-5
   (run_t7.py). SUPERSEDED 2026-08-05: stations are now addressed by (surface, x/c)
   and the target's own Cp curve is interpolated at that x, so the correspondence is
   exact and the guard was removed rather than retained.
3. **Pinned-coefficient framing** (PLAUSIBLE) → reporting split free16/all18.
4. **Release-and-verify absent** (CONFIRMED, protocol) → implemented; result above.
5. **Realisability semantics** (CONFIRMED) → ADR-0004: realisability = inviscid-consistent
   representability (0.0004); viscous model gap logged separately (0.11, diagnostic).
   The gap is model error, not unrealisability — the solve's 1e-11 recovery proves it.
6. **cond category error risk** (CONFIRMED as reporting rule) → ADR-0004: submap cond 90
   (station selection) ≠ extended-system cond 1.6e8 (D-2); never conflate.
7. **ω edge cases unexercised** (CONFIRMED gap) → recover_omega factored out + 5 unit
   tests (α channel, θ fallback exact to 1e-12, ω=0 freeze, degenerate, clipping).
   Reviewer independently validated the mechanism against vendor update_state (3-4 sig figs).

## T4 — pre-solve: closed with ADR-0004 semantics
Representability metric honest and unmasked (reviewer-verified SVD, no rcond
truncation); initializer ratio 0.256; KKT cond 2.4e4; 2-pass chain reached 4.7e-3
from 2.3e-2. Review's FAIL verdict addressed by ADR-0004 (metric was answering the
right question with the wrong label; now labeled and supplemented).

## T5 — extended Newton: closed
DOF accounting (alpha_free paths), FD-over-A columns (5-6 sig figs across step sweep,
no stencil discontinuities), joint-ω mechanism — all survived direct numerical attack.
Caveats folded into ADR-0004 reporting rules and the ω unit tests.

## T6 — diagnostics: closed
D-2 recorded the extended-system conditioning that grounded the review's category-error
caveat; D-6 order estimator matches STATS_PROTOCOL H3; 20 unit tests.

## Sign-off (GATES.md six conditions)
Tests ✅ (fast suite + ω tests; slow T7 pipeline archived with manifest) ·
Domain validation ✅ · Adversarial review ✅ (all CONFIRMED findings fixed and
re-verified by rerun) · Artifacts ✅ · Docs/site/paper ✅ · Merged & pushed ✅
