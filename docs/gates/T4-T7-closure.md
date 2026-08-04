# Gate closure report — T4, T5, T6, T7 (consolidated)

**Closed:** 2026-08-04 · **Evidence:** experiments/results/t7_naca2412/{run.log, diagnostics.json}

## T7 — the falsifiable test (dossier §7.8): PASS
| Criterion | Threshold | Measured |
|---|---|---|
| ‖A−A*‖∞ over the 16 FREE coefficients | < 1e-4 | **1.079e-11** |
| Newton iterations | ≤ 9 | **4** |
| Quadratic tail (D-6) | visible | 5.9e-4 → 3.1e-6 → 1.0e-10 |
| Release-and-verify (natural transition, recovered vs target geometry) | Δcl<1e-3, Δcd<2e-4 | **Δcl=8.0e-13, Δcd=1.1e-14** |

Framing per review: 16 coefficients recovered by Newton; A_u0/A_l0 prescribed
(le_treatment=prescribed) — pinned by design, not recovered.

## Adversarial review (6 attack vectors) — all findings resolved
1. **Circularity** — refuted by the reviewer (perturbation material, no aliasing).
2. **Station-index correspondence** (PLAUSIBLE, implementation-dependent) → explicit
   guard added: max |dx/c| at stations = 6.1e-6, asserted < 2e-5 (run_t7.py).
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
