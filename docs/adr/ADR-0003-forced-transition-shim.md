# ADR-0003: forced-transition (trip) via adapter shim

**Status:** accepted, 2026-08-04

## Context
FM-4 (dossier §4): mfoil's e^n transition closure is C⁰ in the design variables;
the dossier mandates *forced transition during inverse iterations* (converge shape,
then release and verify in direct mode). T1 introspection (docs/mfoil_internals.md §6)
established that mfoil has **no forced-trip API**: transition is always natural,
re-derived each Newton iteration by the free module-level function
`update_transition` (mfoil.py:2507), which flips `M.vsol.turb` when the marched
amplification factor crosses `param.ncrit`.

## Decision
Adapter-level shim (`src/cins/solver/mfoil_adapter.py`), same pattern as ADR-0001:

1. `set_forced_transition(m, xtr_upper, xtr_lower)` — overwrite `m.vsol.turb`
   to 0/1 by comparing each surface node's x/c against the configured trip
   location (configs: `transition.xtr_upper/xtr_lower`), and
2. suppress re-derivation by replacing the *instance path* to
   `update_transition` with a no-op for the duration of inverse iterations
   (module-level reassignment, restored by `release_transition(m)`), after which
   a direct-mode verify solve runs with natural transition.

## Consequences
- The inverse Newton system sees a transition pattern frozen in node-index space —
  the C⁰ kink is removed from the Jacobian, per the dossier's FM-4 mitigation.
- The frozen pattern is expressed on node indices; since the T5 `stgt` discipline
  keeps N and the s-distribution fixed, the trip stays at a fixed arc-length
  station across geometry updates.
- Every T7/T8 result must state the transition mode; released-transition direct
  verification is part of the T7 protocol.
- Module-level reassignment is process-global while active; the adapter restores
  the original function in `release_transition` (and via context manager).
