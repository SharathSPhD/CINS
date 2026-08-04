# ADR-0003: forced-transition (trip) via adapter shim

**Status:** accepted, 2026-08-04. Revised 2026-08-04 (station-equation replacement added;
turb-freezing alone was insufficient — see "Revision" below).

## Context
FM-4 (dossier §4): mfoil's e^n transition closure is C⁰ in the design variables;
the dossier mandates *forced transition during inverse iterations* (converge shape,
then release and verify in direct mode). T1 introspection (docs/mfoil_internals.md §6)
established that mfoil has **no forced-trip API**: transition is always natural,
re-derived each Newton iteration by the free module-level function
`update_transition` (mfoil.py:2507), which flips `M.vsol.turb` when the marched
amplification factor crosses `param.ncrit`.

## Decision
Adapter-level shim (`src/cins/solver/mfoil_adapter.py`), same pattern as ADR-0001.
Two module-level vendor functions are neutralized while forcing is active, both
restored by `release_transition()` (or the `forced_transition` context manager):

1. `set_forced_transition(m, xtr_upper, xtr_lower)` — overwrite `m.vsol.turb`
   to 0/1 by comparing each surface node's x/c against the configured trip
   location (configs: `transition.xtr_upper/xtr_lower`); initialize any
   newly-turbulent node's shear-lag state (`sa`, i.e. `ctau`) via
   `get_cttr`-based ramping, mirroring vendor `update_transition`'s own
   earlier-transition branch; force the wake fully turbulent; refuse (raise
   `ValueError`) if the requested trip would require *laminarizing* an
   already-turbulent node — trips may only move forward of the current
   pattern.
2. Suppress `update_transition` re-derivation: reassign the module-level name
   to a no-op for the duration of inverse iterations (module-level
   reassignment, same shim pattern as ADR-0001), so `M.vsol.turb` stays
   pinned at the pattern `set_forced_transition` installed.
3. **Replace `residual_transition`** (mfoil.py:2623) with
   `_residual_transition_forced` for the duration of inverse iterations.
   `build_glob_sys` (mfoil.py:2125) calls `residual_transition` at exactly
   the station where the (now-frozen) `M.vsol.turb` pattern flips
   (`tran = turb[i-1] ^ turb[i]`). See "Revision" below for why this step is
   required, not optional.

## Modeling choice: `_residual_transition_forced`

Vendor's `residual_transition` is a *natural*-transition closure: it solves an
internal sub-Newton for a station-local point `xt ∈ [x1,x2]` where the marched
amplification factor equals `param.ncrit`, then blends a laminar `[x1,xt]` leg
with a turbulent `[xt,x2]` leg. This equation assumes transition is in fact
governed by amplification reaching `ncrit` somewhere inside the station — which
is false once transition is pinned away from where it would occur naturally
(e.g. amplification is still ≈2, not `ncrit`≈9, at a forced 5%c trip on the
NACA 2412/α=2°/Re=1e6 case).

`_residual_transition_forced` instead treats the whole boundary station
`[x1,x2]` as the onset of turbulence, XFOIL-trip style:

- **Momentum (row 0) and shape-parameter (row 1):** vendor's own
  `residual_station` evaluated directly on `[x1,x2]` with `param.turb=True` —
  the pure-turbulent closure applied across the boundary station, with **no**
  laminar sub-leg and **no** station-local `xt`. This is the standard
  XFOIL-like approximation for a station forced into turbulence, and it is
  exactly the closure the *next* (fully turbulent) station already uses in
  `build_glob_sys`, so the equations are continuous going downstream.
- **Shear-lag row (row 2, `Rlag` inside `residual_station`): REPLACED.** In
  turbulent mode, `residual_station`'s row 2 is a shear-lag ODE relating
  `sa[0]=U1[2]` to `sa[1]=U2[2]`. At an onset station `U1[2]` is the *upstream
  laminar* node's amplification factor, not a shear-stress coefficient, so
  that ODE is not physically meaningful here (confirmed by reading
  `residual_station`'s row assembly, mfoil.py:2915: `R = [Rmom, Rshape,
  Rlag]` — row index 2 is unambiguously the shear-lag/amplification row).
  It is replaced with the same turbulence-onset closure vendor's own
  `update_transition`/`set_forced_transition` use to initialize a
  newly-turbulent node: `U2[2] (ctau) == cttr(U2)` (`get_cttr`, mfoil.py:3004
  — the transition-correlation root-shear-stress value). `cttr` is a function
  of `th/Hk/Ret/ue` at `U2` only (`get_cttr`'s `cttr_U[2]` — the derivative
  w.r.t. `sa` — is structurally zero), so the replaced row depends **only**
  on the downstream state: `R_U[2, 0:4] = 0` (no `U1` dependence) and
  `R_x[2, :] = 0` (no `x` dependence). `R_U[2, 4:8] = e_sa − cttr_U` where
  `e_sa = [0,0,1,0]`.

No station-local `xt` is computed or needed anywhere in the replacement:
because the momentum/shape rows use the station's real endpoints `[x1,x2]`
directly (no laminar/turbulent blend), nothing in the residual depends on
where *within* `[x1,x2]` the natural trip would have occurred. The trip
location is pinned entirely by `set_forced_transition`'s node-index `turb`
pattern, not by any quantity computed inside `_residual_transition_forced`.

## Revision: why turb-freezing alone was insufficient

The original (2026-08-04, first pass) decision froze `M.vsol.turb` and no-op'd
`update_transition` but left vendor `residual_transition` untouched. Empirically
(NACA 2412, α=2°, Re=1e6, trip 5%/5%): the physics moved in the right direction
under Newton pressure (`cd` 0.00578→0.00741) but the solve never converged —
`glob.conv` stayed `False`, `Rnorm` stuck around 12.6 for the full 50-iteration
budget. Root cause: `build_glob_sys` still called the *natural* `residual_transition`
at the frozen boundary station, which internally re-solves `amplification(xt) ==
ncrit` — an equation with no solution consistent with a trip forced where
amplification is nowhere near `ncrit`. That row of the residual could never be
driven to zero, so Newton could shrink every other row but not that one, and
`Rnorm` floored out. `_residual_transition_forced` (above) removes this
inconsistent equation from the residual entirely.

## Consequences
- The inverse Newton system sees a transition pattern frozen in node-index space,
  governed by a physically consistent onset closure at the trip station — the C⁰
  kink is removed from the Jacobian (per FM-4) *and* the boundary-station equation
  is solvable, so the coupled Newton solve actually converges under forcing.
- The frozen pattern is expressed on node indices; since the T5 `stgt` discipline
  keeps N and the s-distribution fixed, the trip stays at a fixed arc-length
  station across geometry updates.
- Empirical validation (NACA 2412, α=2°, Re=1e6, `tests/unit/test_forced_transition.py`):
  - trip 5%/5%: converges (`glob.conv=True`, `Rnorm < param.rtol=1e-10`);
    `cd=0.01125` (natural `cd=0.005778`, strictly greater, as expected from the
    larger turbulent wetted area); `cl=0.4417` vs natural `cl=0.4494` (< 2%
    difference, well within the 10% acceptance band).
  - trip 30%/30%: converges; `cd=0.00788`, strictly between the 5%-trip `cd`
    and the natural `cd` — monotonic in trip location, as physically expected.
  - `release_transition()` then re-solving from the same (still-forced-state)
    `m` reproduces the pinned natural baseline (`test_t0_baseline.py`) to
    within its stated tolerance: `cl=0.449351±1e-3`, `cd=0.005778±2e-4`.
  - Rebuilding `build_glob_sys` after a converged forced solve (shim still
    active) reproduces `‖R‖ < 1e-8` — the converged state is a genuine fixed
    point of the forced residual, not an artifact of the Newton step sequence.
- Every T7/T8 result must state the transition mode; released-transition direct
  verification is part of the T7 protocol.
- Both shims are module-level reassignments and are **process-global** while
  active — every `mfoil` instance in the process is affected, not just the one
  passed to `set_forced_transition`. Callers (and tests) must always pair
  `set_forced_transition`/manual restore with `release_transition()`, or use
  the `forced_transition` context manager, to avoid leaking the shim into
  unrelated solves. `release_transition()` restores BOTH `update_transition`
  and `residual_transition` to the original vendored functions.
