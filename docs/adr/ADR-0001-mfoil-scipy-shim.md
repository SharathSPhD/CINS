# ADR-0001: scipy≥1.11 compatibility shim for vendored mfoil (no vendor edit)

**Status:** accepted, 2026-08-04

## Context
mfoil v2023-06-28, `build_glob_sys` line 2059:
```python
if (M.glob.realloc) or (type(M.glob.R_x) == list) or not (M.glob.R_x == (3*Nsys, Nsys)):
```
compares a `scipy.sparse` matrix to a shape tuple (missing `.shape`, unlike the
correct comparisons for `R` and `R_U` just above). With scipy ≥ 1.11 the sparse
`__eq__` attempts elementwise broadcast and raises
`ValueError: operands could not be broadcast together`. The viscous coupled solve
crashes on Newton iteration 2 (iteration 1 passes because `R_x` is still a list).

## Decision
Vendor policy forbids editing `vendor/mfoil/mfoil.py`. Instead the adapter
(`src/cins/solver/mfoil_adapter.py`) swaps `m.glob.__class__` to a `Glob` subclass
whose `realloc` property always returns `True`, short-circuiting the broken
comparison every iteration.

## Consequences
- `R`, `R_U`, `R_x`, `R_V` are freshly allocated (`lil_matrix`) each Newton
  iteration instead of being zeroed in place. mfoil pays this cost on iteration 1
  anyway; measured impact at npanel=199 is negligible for Stage 1.
- All CINS code must construct solvers via `make_mfoil()` so the shim is applied
  (enforced by the vendor-access rule in project CLAUDE.md).

## Alternatives rejected
- Editing the vendor file: breaks provenance and the "unmodified upstream" claim.
- Pinning scipy < 1.9: conflicts with modern numpy and the rest of the stack.
- Reporting upstream and waiting: we will report it (the Matlab version and the
  2026 mfoil.m release may already fix it), but the build cannot block on it.
