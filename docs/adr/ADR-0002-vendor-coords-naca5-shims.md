# ADR-0002: adapter shims for two vendored mfoil input bugs (no vendor edit)

**Status:** accepted, 2026-08-04

## Context
Two unconditional `TypeError`s in mfoil v2023-06-28, found during T1/T2:

1. **`set_coords` (mfoil.py:1249-1272):** `X.shape(1)` calls the shape *tuple*
   instead of indexing it — `mfoil(coords=...)` fails for any input. CST-driven
   geometry (the whole point of CINS) requires the coords path.
2. **`naca_points` 5-digit branch:** `mv = [...]; m = mv(n)` and `cv(n)` call
   Python lists as functions — every 5-digit NACA code (e.g. '23012') fails.

## Decision
Both routed around in `src/cins/solver/mfoil_adapter.py` (vendor untouched):
- `make_mfoil(coords=...)` constructs a placeholder instance and applies
  `_set_coords_fixed` — the vendor routine's exact semantics (orientation check
  via signed area, chord from x-extent, re-panel via vendor `make_panels`) with
  the typo fixed.
- `make_mfoil(naca='XXXXX')` (5 digits) generates coordinates with
  `naca5_points` — the vendor's 5-digit formula with list indexing fixed
  (`mv[int(n)-1]`) — and routes through the coords path.

Tests use the facade; `tests/_mfoil_coords.py` / `tests/_naca5.py` are thin
aliases kept for import stability.

## Consequences
- 4-digit NACA construction still uses the vendor path unchanged (baseline
  regression tests unaffected).
- Both bugs to be reported upstream to K. Fidkowski (the 2026-02-17 Matlab
  release may already fix them; the Python port lags).
