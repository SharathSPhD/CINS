# T9 — Stage 2 (cascade) design review

**Date:** 2026-08-04 · **Input:** dossier §8, Stage 1 evidence (gates T0–T8) ·
**Decision owner:** project

## What Stage 1 established that changes §8's plan

1. **The architecture claim transfers as-is.** The extended-system machinery
   (FD-over-A geometric block, joint under-relaxation, viscous-state-preserving
   geometry hook, onset-closure trip) is solver-structural, not airfoil-specific.
   The cascade adds boundary conditions and a kernel, not new coupling ideas.
2. **Identifiability must be designed in from day one.** The QR-pivoted station
   selection (T7/T8's central finding) becomes MORE important in cascades: surface
   Mach targets on high-turning blades have long low-sensitivity stretches
   (covered passage). The Stage 2 spec must treat station selection as part of the
   problem definition, not a tuning knob.
3. **The honest baseline matters.** H2 showed modern LM is strong; Stage 2's
   benchmark must pair against warm- and cold-started LM from the start, and the
   flow-solve ledger (instrumentation.py) carries over unchanged.

## Decisions (dossier §8 options resolved)

| Question | Decision | Rationale |
|---|---|---|
| Periodic kernel | **ln → ln·sin substitution with adaptive-quadrature panel integrals first** (§8.2); analytic integrals only if quadrature dominates runtime | Safety first; s→∞ regression gives an exact correctness oracle against Stage 1 |
| Inlet/outlet BC | Inlet angle prescribed, outlet angle unknown (+ cascade Kutta row Γ = s·ΔV_t) | Turbine-analysis convention; DOF re-assertion required (FM-1 discipline) |
| Compressibility | Accept subcritical (Kármán–Tsien) for Stage 2; transonic deferred to MISES (Stage 3) | §8.5; no cheap fix inside a panel method |
| AVDR/streamtube | Defer to Stage 3 | Not needed for the Gostelow validation ladder |
| Validation ladder | (1) s=10⁶ reproduces Stage 1 EXACTLY (pinned regression); (2) Gostelow analytic cascades — THE Stage 2 gate; (3) LS89 GEOMETRY-side validation only in Stage 2 (fit/paneling/inverse self-consistency on the section); the MUR pressure-distribution comparisons move to Stage 3 — the closure review computed peak isentropic Mach 0.964–1.227 across all 7 in-repo MUR datasets (mur43–49), i.e. locally transonic-to-supersonic, outside the Kármán–Tsien subcritical scope this same document commits to (amended per adversarial check, 2026-08-05); (4) MULTALL cross-check | §8.4 + LS89 scope corrected |
| Geometry basis | CST unchanged; stagger/pitch as rigid-body parameters outside A (absorption modes per FM-1 bookkeeping) | Keeps dsurface_dA design-independent |

## Work breakdown (Stage 2 gates, mirroring T-ladder discipline)

- **S0** Periodic kernel module + s→∞ regression gate (exact Stage 1 reproduction)
- **S1** Cascade BC rows + DOF re-assertion (inlet prescribed / outlet free / Kutta)
- **S2** Gostelow inviscid validation gate (surface-velocity RMS threshold from the
  published exact solutions; pre-register before running)
- **S3** Viscous cascade at subcritical conditions (synthetic + Gostelow-derived
  loadings); LS89 limited to geometry-side checks — the in-repo MUR conditions are
  locally transonic (peak M_is 0.96–1.23, computed from the repo data) and belong
  to Stage 3/MISES (amended per the closure review's adversarial check)
- **S4** Cascade inverse: falsifiable test T7-analog (self-generated surface-Mach
  target, QR station selection, release-and-verify) — targets: Mach RMS < 0.005,
  outlet angle < 0.1° (§8.6, calibrated to Lavagnoli's KAN benchmarks)
- **S5** Benchmark vs warm/cold LM + report

## Risks carried forward
- Wake periodicity/branch cuts in the ln·sin kernel (streamfunction branch
  handling was already delicate in the isolated case — see panel_linsource_stream).
- Stagnation tracking with high turning (Istag jumps; the ±5-index remap guard
  may need widening).
- The trip-onset closure at high acceleration (turbine suction side) — validate
  against LS89 transition behavior before trusting FM-4 mitigation there.

**Gate T9 closes** when this review is adversarially checked and the S0 spec is
frozen in docs/SPEC.md (Stage 2 addendum).
