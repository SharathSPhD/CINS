# TRIZ log — FM-4: physical transition vs smooth Jacobian

**Date:** 2026-08-04 · **Matrix cell:** improving 27 (Reliability) vs worsening 28
(Model accuracy) → principles 32, 3, 11, 23.

**Contradiction.** The monolithic Newton system needs a smooth, *consistent*
residual (convergence reliability), but mfoil's transition closure is the natural
e^n amplification model — the transition-station equation itself enforces
n(x_t) = n_crit via an internal sub-Newton. Freezing the lam/turb flags (naive
trip) leaves that equation inconsistent with the frozen pattern: residual norm
stalls (~12.6, flat) even as the physics (cd) moves correctly.

**Resolution — separation in time (+ P11 beforehand cushioning, P23 feedback).**
- *During inverse iterations:* replace the station equation with the smooth
  turbulence-onset closure sa₂ = ctau_init(U₂) at a fixed trip location
  (XFOIL-style forced transition), eliminating the C⁰ kink FM-4 warns about.
- *After shape convergence:* restore the natural closure and run a direct-mode
  verification solve (feedback), so no accuracy is ultimately sacrificed.
- Both phases via adapter-level module shims (ADR-0003); vendor code untouched.

**Paper thread (P1 Discussion).** The dossier's FM-2/FM-3/FM-4 mitigations are
all instances of TRIZ separation principles: FM-3 prescribed-LE = separation in
space; FM-4 trip-then-release = separation in time; FM-2 orthogonalized basis =
principle 3 (local quality). This section documents the pattern as it is used.
