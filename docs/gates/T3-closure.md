# Gate closure report — T3: constraint rows

**Closed:** 2026-08-04 · **Branch:** main · **Owner:** main session

## Evidence
| Criterion | Threshold | Measured | Verdict |
|---|---|---|---|
| area_row vs adaptive quadrature (fitted NACA 2412, incl. nonzero TE gap) | < 1e-10 | ~2.8e-17 | PASS |
| Per-term Bernstein Beta integrals vs quadrature | < 1e-12 | PASS | PASS |
| te_wedge_row vs fitted TE slope, both sides | independent | 5e-6 agreement | PASS |
| le_radius_row vs published 4-digit nose radius | few % | 1.6% | PASS |

## Reviews
- **Aero-adversary: 1 CONFIRMED finding — lower-surface sign error in te_wedge_row.**
  Code returned tan(β)+ζ_T for both sides; the exact identity ζ'(1) = ζ_T − A_n
  (N2=1) requires ζ_T − tan(β) for the lower surface. Numerically demonstrated
  against fitted NACA 2412 (code: +0.078 vs actual A_l,n = −0.080). **Fixed**
  (constraints.py) and pinned by a new independent test recovering A_n from the
  numerical TE slope on both surfaces (5e-6 agreement). Root cause of invisibility:
  the original unit test asserted the code's own formula — replaced. The same
  coverage gap was closed for le_radius_row (nose-radius cross-check).
- PLAUSIBLE (not blocking): shared_le_radius_row documents the A_l0<0 assumption;
  no realistic counterexample constructed. Revisit if reflex/negative-camber
  sections enter the panel.
- Beta-function algebra, TE-term sign and asymmetric n_u≠n_l verified independently
  by the reviewer to 2.8e-17 — attack failed (correct).

## Notes
curvature_derivative_continuity_row (G3) deliberately raises NotImplementedError
until derived and verified — optional per dossier §3.3.

## Sign-off
Tests ✅ · Domain validation ✅ · Adversarial review ✅ (finding fixed + re-verified) ·
Artifacts ✅ · Docs/site ✅ · Pushed ✅
