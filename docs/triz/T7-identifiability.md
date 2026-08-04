# TRIZ log — T7: square-system determinism vs point-sample identifiability

**Date:** 2026-08-04 · **Principles applied:** 3 (local quality), 16 (partial/
excessive action), 25 (self-service).

**Contradiction.** The hypothesis demands a *square, determined* system
(M targets + K constraints = n_A_free (+1 if α free)) — no least squares, no
optimization. But M point samples of Cp discard between-station information:
with evenly-spaced stations the 16×16 station sensitivity submap had condition
~10⁷, i.e. near-null coefficient directions whose motion changes the sampled Cp
by less than float precision. Newton then converges to *any* of several exact
roots: recovery stalled at 1.4e-3–6e-2 with the target rows at exact zero.
Adding stations would fix the information deficit but over-determine the system
— reintroducing the optimization the architecture forbids.

Two contributing null-direction families were eliminated first, each verified
empirically:
- **Camber–α equivalence:** freeing α (meant for arbitrary-target absorption)
  lets a slightly different camber at a slightly different α interpolate the
  same samples → α fixed for self-consistency tests.
- **Prescribed-LE mismatch:** excluding LE stations (FM-3) while leaving the
  LE-dominant coefficients free leaves A₀ unobservable → prescribe (fix) the
  LE coefficients, not just drop the stations.

**Resolution.** Keep the system square; make each equation maximally
informative. The T4 pre-solve already builds the full (200 × n_A) sensitivity
matrix for initialization — reuse it (principle 25) to *select* the M stations
by QR column pivoting (principles 3/16): the chosen rows maximize the square
submap's conditioning. Result: cond 10⁷ → 90.3; recovery 1.4e-3 → **1.1e-11**;
4 Newton iterations. Full-curve information enters only through the linear
pre-solve; the nonlinear solve stays square and determined.

**Paper thread (P1).** This is a new methodological contribution beyond the
dossier: *sensitivity-optimal station selection as the identifiability guard
for determined inverse systems* — the practical answer to §7.10's
non-uniqueness caveat without abandoning the root-finding architecture.
