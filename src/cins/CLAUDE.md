# src/cins — math conventions (BINDING)

Every constraint row and Jacobian block depends on these. Change requires an ADR.

## CST conventions
- ψ = x/c ∈ [0,1], ζ = z/c. Class function C(ψ) = ψ^N1 (1−ψ)^N2, default N1=0.5, N2=1.0.
- Surface: ζ(ψ) = C(ψ) Σᵢ Aᵢ Sᵢ(ψ) + ψ ζ_T, Bernstein Sᵢ(ψ) = Kᵢ ψⁱ(1−ψ)^(n−i).
- **Lower-surface coefficients are stored with their natural (negative) sign.**
  A_l,i < 0 for a conventional airfoil. The shared-LE row is A_u0 + A_l0 = 0.
- Coefficient vector ordering: `A = [A_u0..A_un, A_l0..A_ln]` (upper block first).
- ζ_T upper/lower: half TE gap each, ζ_T,u = +gap/2, ζ_T,l = −gap/2.

## Geometry / paneling
- Node ordering follows mfoil: **TE lower → LE → TE upper, counterclockwise** (mfoil
  asserts CCW in build_wake; introspection note in docs/mfoil_internals.md is authoritative).
- Cosine spacing in ψ for CST sampling; mfoil re-panels with its own spline_curvature.

## Numerics
- `dsurface_dA` is design-independent: assemble once per (ψ-grid, n), cache; never rebuild
  inside a Newton loop.
- Beta-function closed forms via `scipy.special.beta`; no numerical quadrature in
  production constraint rows (quadrature appears only in tests as the independent check).
- DOF accounting assertion M + K = n_A + 1 raises at construction. Log numbers every run.

## Style
- Pure functions in `cst/`; classes only where state caching demands (basis cache, adapter).
- Type hints everywhere; numpy arrays documented with shape comments `# (npts, n+1)`.
- No `print` — use `logging`. No hardcoded parameters — everything from `cins.config`.
