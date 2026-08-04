# mfoil internals — T1 introspection notes

Vendored source: `vendor/mfoil/mfoil.py`, version string `M.version = '2022-02-22'` (file header
comment says `v2023-06-28`; the string embedded in the code itself is stale — noted for the
record, not load-bearing). ~3940 lines, single module, no external state beyond the `mfoil`
object graph (`M.geom`, `M.foil`, `M.wake`, `M.oper`, `M.isol`, `M.vsol`, `M.glob`, `M.post`,
`M.param`).

**Method**: every claim below was checked by running `.venv/bin/python` against
`cins.solver.mfoil_adapter.make_mfoil` (NACA 2412, 80 panels, `alpha=3°`, `Re=2e5`, viscous),
inspecting live attribute shapes/dtypes, and by reading the corresponding vendor source lines
(cited as `mfoil.py:LINE`). Where the dossier (`docs/CST_MISES_Monolithic_Inverse_Design.md`
§7.2/§7.6) made a specific claim, it is checked against the code and any discrepancy is called
out explicitly.

Do not edit `vendor/mfoil/mfoil.py`. All adapter-side workarounds documented here belong in
`src/cins/solver/mfoil_adapter.py`, following the ADR-0001 pattern (subclass/monkeypatch from
outside, never touch the vendor file).

---

## 1. Global system

### 1.1 State vector

`M.glob` is the `Glob` class (`mfoil.py:99-110`):

```
S.Nsys = 0      # number of equations and states
S.U    = []     # primary states (th,ds,sa,ue) [4 x Nsys]
S.dU   = []     # primary state update
S.dalpha = 0.   # angle of attack update
S.conv = True
S.R    = []     # residuals [3*Nsys x 1]
S.R_U  = []     # residual Jacobian w.r.t. primary states
S.R_x  = []     # residual Jacobian w.r.t. xi (s-values) [3*Nsys x Nsys]
S.R_V  = []     # global Jacobian [4*Nsys x 4*Nsys] (+1 row/col if cl-constrained)
S.realloc = False
```

Verified live: for NACA 2412 @ 80 panels, `M.foil.N = 81`, `M.wake.N = 19`,
`M.glob.Nsys = 100 = N + Nw` (`mfoil.py:2315`, `init_boundary_layer`:
`M.glob.Nsys = M.foil.N + M.wake.N`). `M.glob.U.shape == (4, 100)` confirmed.

Row order within each column is **`[theta, delta*, sa, ue]`** where `sa` is the amplification
factor `n` for laminar stations or `sqrt(ctau)` for turbulent stations (comment at
`mfoil.py:102`, `mfoil.py:131` `Post.sa`). Column order is node index, and node index runs over
**airfoil nodes 0..N-1 then wake nodes N..N+Nw-1** — the wake is *not* a separate array in the
`U`/`R` bookkeeping, it is appended.

Node index 0..N-1 ordering (verified against `identify_surfaces`, `mfoil.py:1653-1662`, and the
CCW assertion in `build_wake`, `mfoil.py:748`): **index 0 = trailing edge on the lower surface,
increasing index moves along the lower surface toward the leading edge, crosses the stagnation
point somewhere in `[Istag[0], Istag[1]]`, then continues up the upper surface to index N-1 =
trailing edge on the upper surface.** This matches `src/cins/CLAUDE.md`'s stated convention
("TE lower → LE → TE upper, CCW") — confirmed, not just asserted.

Three "surfaces" partition the Nsys nodes for residual assembly (`mfoil.py:1660-1662`):

```
M.vsol.Is = [range(Istag[0], -1, -1),      # si=0: lower surface, walking stag→TE(lower)
             range(Istag[1], N),           # si=1: upper surface, walking stag→TE(upper)
             range(N, N + Nw)]             # si=2: wake
```

### 1.2 Residual R(U)

`M.glob.R` has shape `(3*Nsys,)` — **3 equations per node**, not 4. Verified live:
`R_x.shape == (300, 100)` for Nsys=100, i.e. `3*Nsys x Nsys`; `R_U.shape == (300, 400)`, i.e.
`3*Nsys x 4*Nsys`. Built in `build_glob_sys` (`mfoil.py:2031-2163`).

The three per-node residual rows, from `residual_station` (`mfoil.py:2724-2919`, returns
`R = [Rmom, Rshape, Rlag]`):

1. **Momentum-integral equation** (`Rmom`, `mfoil.py:2890`) — closes on `theta`.
2. **Shape-parameter (kinetic-energy) equation** (`Rshape`, `mfoil.py:2909`) — closes on `ds`
   (delta*).
3. **Amplification / shear-lag equation** (`Rlag`, `mfoil.py:2850` turbulent shear-lag or
   `mfoil.py:2872` laminar amplification-factor ODE) — closes on `sa`.

Each of the three rows is evaluated as a **two-point finite-volume-style station residual**
between adjacent nodes `i-1, i` on a surface (`Ip = [i-1, i]` at `mfoil.py:2123`); the outer loop
in `build_glob_sys` accumulates these into the global `3*Nsys` vector by node.

### 1.3 The 4th unknown (`ue`) and how it closes

`ue` (row 3 of `U`) has **no equation among the 3 per-node residual rows** described above —
those close `theta, ds, sa` only. The 4th equation per node is the **mass-conservation / edge-
velocity coupling**, assembled separately in `solve_glob` (`mfoil.py:1935-1996`), not in
`build_glob_sys`:

```python
# mfoil.py:1974
R = np.concatenate((M.glob.R, ue - (ueinv + M.vsol.ue_m @ (ds*ue))))
```

i.e. `R_ue = ue - (ueinv + ue_m @ (ds*ue))` — the classic viscous/inviscid interaction law
(edge velocity = inviscid edge velocity + linearized correction from displacement-thickness-
induced transpiration "mass" `m = ds*ue`, through the panel mass-influence matrix `ue_m`,
`mfoil.py:1472-1623`). This is why `M.glob.R_V` (the matrix actually factorized) is
`(4*Nsys [+1], 4*Nsys [+1])` (`mfoil.py:1962-1964`), built by stacking `R_U` (3Nsys×4Nsys) on top
of the `d(R_ue)/dU` block (`mfoil.py:1978-1981`):

```python
M.glob.R_V[0:3*Nsys, 0:4*Nsys] = M.glob.R_U
I = slice(3*Nsys, 4*Nsys, 1)
M.glob.R_V[I, Iue] = sparse.identity(Nsys) - M.vsol.ue_m @ np.diag(ds)   # d R_ue / d ue
M.glob.R_V[I, Ids] = -M.vsol.ue_m @ np.diag(ue)                          # d R_ue / d ds
```

So the "3*Nsys residual" of `build_glob_sys` and the augmented "4*Nsys residual" solved by
`solve_glob` are two different objects; `M.glob.R`/`R_U`/`R_x` only ever hold the 3-row-per-node
piece, and the ue-row is always assembled on the fly inside `solve_glob`. **This is important
for T5**: the flow residual `R(U; x(A))` that the dossier's extended Newton system wants (§7.6)
is the 4·Nsys object (`R` concatenated with the ue-row), not `M.glob.R` alone.

### 1.4 Extra α unknown / cl-driver

`M.oper.givencl` (default `False`, `mfoil.py:61`) selects the mode. When
`M.setoper(cl=...)` is used, `givencl=True` and an extra unknown `dalpha` / extra equation
`Rcla = cl - cltgt` is appended (`clalpha_residual`, `mfoil.py:2000-2027`;
`solve_glob:1983-1988`):

```
docl = M.oper.givencl
NN = 4*Nsys + docl
...
if docl:
    R = concat(R, Rcla)
    R_V[I, 4*Nsys] = Ru_alpha      # d(ue residual)/d(alpha)
    R_V[4*Nsys, :] = Rcla_U        # d(cl residual)/d(U), d(cl residual)/d(alpha)
```

In the default alpha-prescribed mode (`givencl=False`, the mode we will use for T5 since the
dossier's α is a genuine extra unknown driven by the CST target-Cp system, not by an mfoil cl
target), **`solve_glob` does not add a row/column at all** — `R_V` stays `4*Nsys x 4*Nsys` and
`M.glob.dalpha` is never populated by the linear solve; `update_state` still does
`M.oper.alpha += omega*M.glob.dalpha` (`mfoil.py:1911`) but `dalpha` simply stays at its
initialized value (0) in that mode. **Implication for T5**: mfoil's own `α` machinery
(`clalpha_residual`) is cl-targeting, not usable directly for the CST inverse-design's α-as-extra-
unknown scheme; T5's `[∂R/∂α]` column must be assembled independently (α enters only through
`ueinv = get_ueinv(M)`, which is `sgnue * gamref @ [cos α, sin α]`, `mfoil.py:576-584` — cheap,
analytic, does not require touching mfoil's cl-constraint path at all).

### 1.5 Under-relaxation / limiter (`update_state`, `mfoil.py:1837-1932`)

Single scalar `omega`, initialized to 1, reduced by six independent checks (each only lowers
`omega`, never raises it):

1. **theta/ds 50% floor** (`mfoil.py:1857-1865`) — exactly the dossier's claim, verified:
   ```python
   for k in range(2):        # k=0: theta, k=1: ds
       fmin = min(dUk/Uk)     # most negative fractional update
       om = abs(0.5/fmin) if (fmin < -0.5) else 1.
   ```
   i.e. no node's `theta` or `ds` is allowed to drop by more than 50% in one Newton step.
2. Negative-`sa` guard (turbulent `ctau` / laminar `amp`) — skips very-small-amp and small-`ctau`
   nodes as "too restrictive to limit" (`mfoil.py:1870-1871`), else caps at 80% depletion
   (`mfoil.py:1874`).
3. Amplification-factor step cap: `|domega| <= 2` at laminar nodes (`mfoil.py:1879-1886`).
4. `ctau` step cap: `|domega| <= 0.05` at turbulent nodes (`mfoil.py:1888-1894`).
5. `ue` step cap: `|domega| <= 0.2*Vinf` (`mfoil.py:1896-1902`).
6. `alpha` step cap: `|domega| <= 2 deg` (`mfoil.py:1904-1906`).

Then `U += omega*dU; alpha += omega*dalpha` (`mfoil.py:1910-1911`).

**Hk floor — discrepancy vs. the dossier found.** After applying the update, mfoil clamps `Hk`
per surface (`mfoil.py:1913-1924`):

```python
for si in range(3):
    Hkmin = 1.00005 if (si == 2) else 1.02     # si==2 is the WAKE (see Is list, §1.1)
    ...
    if Hk < Hkmin: U[1,j] += 2*(Hkmin - Hk)*U[1,j]   # bump ds to push Hk back up
```

The dossier (§7.2 table) states "Hk > Hk,min ≈ 1.00005 on the airfoil, 1.02 in the wake" — **the
code has it the other way round**: `1.00005` applies to the **wake** (`si==2`), `1.02` to the
**airfoil** surfaces (`si==0,1`). This was verified by reading `identify_surfaces`
(`mfoil.py:1660-1662`: `Is[2]` is the wake range) alongside line 1915. Separately, the *internal*
Hk clipping used throughout `get_Hk`/`get_cteq`/`get_cf`/`get_Us` (e.g. `mfoil.py:2989-2990`,
`3074-3075`, `3698-3699`, `3728`) uses a **different pair of floors**: `1.00005` in the wake,
`1.05` (not `1.02`) on the airfoil. So there are two distinct Hk floors in the code — the
post-Newton-step repair floor (1.00005 wake / 1.02 airfoil, `update_state`) and the
per-evaluation clamp used inside every closure-relation call (1.00005 wake / 1.05 airfoil,
`get_Hk` and friends). Both exist; neither matches the dossier's phrasing exactly. Use the code,
not the dossier, if this ever matters numerically for T5/T6.

7. Negative-`ctau` repair after the floor fix (`mfoil.py:1926-1929`).
8. `rebuild_isol(M)` is called if `|omega*dalpha| > 1e-10` (`mfoil.py:1932`) — i.e. any nonzero
   alpha change triggers an inviscid rebuild (see §7 below).

---

## 2. Geometry chain

### 2.1 `mfoil.__init__` → panels

```python
# mfoil.py:183-198
if coords is not None:
    set_coords(M, coords)
else:
    naca_points(M, naca)
make_panels(M, npanel, None)
```

`M.geom.xpoint` (raw input points, 2×npoint) is a **separate array from `M.foil.x`** (the panel
nodes actually used by the solver, 2×N where N = npanel+1). `make_panels` **always re-splines**
the input points and re-samples them (`make_panels`, `mfoil.py:837-856` → `spline_curvature`,
`mfoil.py:1329-1386`):

```python
def make_panels(M, npanel, stgt):
    clear_solution(M)
    M.foil.x, M.foil.s, M.foil.t = spline_curvature(M.geom.xpoint, npanel+1, Ufac=2, TEfac=0.1, stgt)
    M.foil.N = M.foil.x.shape[1]
```

`spline_curvature` fits a natural cubic spline through `Xin` (`spline2d`, `mfoil.py:1390+`), then
either (a) if `stgt is None`: computes a **curvature-weighted arclength distribution** (denser
where curvature/TE-proximity is high, `mfoil.py:1354-1379`) and samples N points from it, or
(b) if `stgt` is given: evaluates the *same refit spline* at the caller-supplied `s` values
(`mfoil.py:1380-1384`, `s = stgt`), i.e. **the panel node count and s-distribution are exactly
whatever was passed in**, independent of curvature.

**This re-paneling is a bug hazard for CST-driven geometry, verified live**:

```python
# spline_curvature, mfoil.py:1354
if (stgt == None):
```

If `stgt` is a `numpy.ndarray` with more than one element, `stgt == None` broadcasts to an
elementwise boolean array, and the subsequent `if` raises
`ValueError: The truth value of an array with more than one element is ambiguous.` — **confirmed
by direct test**: calling `spline_curvature(Xin, N, Ufac, TEfac, stgt=array_of_101_floats)`
throws exactly this. **Workaround, verified to work**: pass `stgt` as a **plain Python list**,
not an ndarray — `list == None` evaluates to a scalar `False` (no elementwise broadcast), so
`stgt = list(M.foil.s)` round-trips correctly and reproduces the identical `S` array
(`np.allclose` confirmed). Do this conversion in the adapter, never edit `spline_curvature`.

**Second, independent bug found in `set_coords`** (`mfoil.py:1249-1273`, used whenever
`make_mfoil(coords=...)` is called): lines 1267 and 1271 call `X.shape(1)` (parenthesis) instead
of `X.shape[1]` (brackets) — `ndarray.shape` is a tuple, not callable. **Confirmed by direct
test**: `make_mfoil(coords=some_2xN_array)` raises `TypeError: 'tuple' object is not callable`
unconditionally, for *any* coordinate input. `set_coords` is therefore completely unusable as
shipped. **Implication for T2/T5's CST geometry feed**: do not route CST-generated coordinates
through `mfoil.set_coords`/`mfoil(coords=...)`. Instead, from the adapter, set
`M.geom.xpoint`, `M.geom.npoint`, `M.geom.chord` directly (the three lines `set_coords` was
supposed to produce — CCW-orientation check included, `mfoil.py:1265-1268`, itself fine, only the
two `.shape(1)` calls are broken) and then call `make_panels(M, npanel, stgt)` directly. This is
exactly the "geometry update hook" §7 needs anyway.

**Recommendation for the T5 per-Newton-iteration geometry update**:
```python
M.geom.xpoint = new_xy            # from cst.geometry.coords_from_A(...)
M.geom.chord  = new_xy[0,:].max() - new_xy[0,:].min()
make_panels(M, npanel, list(M.foil.s))   # stgt as a *list* keeps N and the s-distribution fixed
```
This keeps `M.foil.N` (hence `Nsys`, hence the sizes of `U`, `R`, all Jacobians) **constant across
Newton iterations** — essential, since a changing `Nsys` would invalidate the whole sparse
system bookkeeping mid-solve. It does *not* keep node **positions** fixed (they move with the new
CST shape, as intended) — only their **arclength fractions relative to the previous panel
geometry**, which is a reasonable, standard re-paneling discipline.

### 2.2 Where geometry `x` enters the residual

Traced exhaustively through the call graph. `x = M.foil.x` (and derived `M.foil.s`, `M.wake.x`)
feeds the solve through **five independent paths**:

1. **AIC / `gamref` (inviscid vortex sheet)** — `build_gamma` (`mfoil.py:609-667`). Assembles the
   `(N+1)x(N+1)` streamfunction influence matrix `M.isol.AIC` from panel geometry via
   `panel_linvortex_stream`/`panel_constsource_stream` (`mfoil.py:966-1030`), each of which calls
   `panel_info` (`mfoil.py:885-919`) → **`atan2(z,x)`** (`mfoil.py:916-917`) for panel angles.
   Solves `AIC @ g = rhs` for `gamref` (0°/90° reference vorticity, `mfoil.py:664-666`).
   `M.isol.gam = gamref @ [cos α, sin α]` (α-linear combination, cheap).
2. **Stagnation point → `xi` mapping** — `stagpoint_find` (`mfoil.py:781-808`): finds the panel
   where `gam` changes sign, interpolates `sstag`/`xstag`, and sets
   `M.isol.xi = concat(|s - sstag|, wake_s - sstag)` — arclength distance from the stagnation
   point at every node, airfoil and wake. `gam` (hence stagnation location) depends on `x` via
   `AIC`/`gamref` above; `s` depends on `x` via the spline/panel geometry directly.
3. **`ue_m` mass-influence matrices** — `calc_ue_m` (`mfoil.py:1472-1623`). Builds `Cgam` (wake
   velocity sensitivity to airfoil `gamma`, calls `inviscid_velocity` → `panel_*` functions),
   `B`/`Bp` (airfoil streamfunction sensitivity to source strength, needs `AIC` again), `Csig`
   (wake velocity sensitivity to source strength) — **all panel-geometry functions, all routed
   through `panel_info`/`atan2`**. Final `ue_m = diag(sgnue) @ ue_sigma @ sigma_m`
   (`mfoil.py:1623`), shape `(Nsys, Nsys)`, dense (not sparse; verified `Nsys=100` case).
4. **Wake trajectory** — `build_wake` (`mfoil.py:723-778`): marches wake points by a
   predictor-corrector integration of `inviscid_velocity(M.foil.x, gam, ...)`
   (`mfoil.py:753-759`) — geometry-dependent both through the airfoil panels it queries and
   through the TE point it starts from (`mfoil.py:745-749`).
5. **`R_x` (arc-length linearization inside `residual_station`/`residual_transition`)** — see §3.

Additionally, `M.geom.chord` (from `x`-extent) rescales `Cp` integration and moment reference,
and `TE_info(M.foil.x)` (`mfoil.py:859-883`) drives the TE-gap/blunt-TE source-panel corrections
used in both (1) and (3).

---

## 3. KEY QUESTION A — is dR/dx available analytically?

**Short answer: no, not completely, and the gap is exactly the part the CST hypothesis cares
about most (the AIC/inviscid coupling). `M.glob.R_x` is real but partial. An analytic
`dR/dA = R_x · dx/dA` chain rule is NOT a correct full derivative; it must be supplemented by
rebuilding the geometry-dependent operators (AIC, `ue_m`, wake, stagnation) and differencing
those — i.e. the dossier's fallback (§7.6) is the actually-necessary path, not merely a
fallback.**

### 3.1 What `R_x` covers

`M.glob.R_x`, shape `(3*Nsys, Nsys)`, is assembled inside `build_glob_sys`
(`mfoil.py:2031-2163`) as the **partial derivative of the per-station residual with respect to
the arc-length-distance-from-stagnation argument `xi`** that `residual_station`/
`residual_transition` take as an explicit input (`x` parameter, `mfoil.py:2724`,
`mfoil.py:2623`). Concretely, inside `residual_station`, `R_x` comes from terms like
`xlog = log(x2/x1)`, `dx = x2-x1`, and the `cfxt`/`cDixt` closures that take `x` as an argument
(`get_cfxt`, `mfoil.py:3396-3414`; `get_cDixt`, `mfoil.py:3476+`) — pure algebraic dependence on
the *distance between two stations*, holding the states `U` fixed. It says nothing about how the
BL edge velocity, `theta`, `ds` at those stations would themselves change if the geometry moved
(that coupling lives in `R_U` and, separately and *not* geometry-complete, in `ue_m`).

`build_glob_sys` additionally propagates `R_x` into `R_U` for exactly one geometric effect — the
**stagnation-point-location dependence of every node's `xi`** — via the explicit chain rule at
`mfoil.py:2146-2160`:

```python
# R_ue += R_x * x_st * st_ue      (x_st = -sgnue; st = stagnation point)
x_st = np.concatenate((-M.isol.sgnue, -np.ones(Nw)))
R_st = M.glob.R_x @ x_st[:, None]
M.glob.R_U[:, Iue[Istag[0]]] += R_st * st_ue[0]
M.glob.R_U[:, Iue[Istag[1]]] += R_st * st_ue[1]
```

i.e. mfoil already knows that *as the Newton iteration moves `ue` at the two stagnation-bracket
nodes, the stagnation point moves, therefore every node's `xi` moves, therefore the residual
moves* — but this is a **fixed-geometry** effect (stagnation motion *within* a converged panel
mesh, driven by the flow unknowns, not by node coordinates). It is unrelated to `dR/dx` in the
"node coordinates change" sense §7.2 is asking about; it is included here as a live example of
how mfoil *would* propagate an `R_x` term if it had one for `dx/dA`, and it is exactly this
pattern that gets exploited if `R_x` were extended.

### 3.2 What `R_x` misses (all geometry-critical)

`R_x` is computed entirely inside `residual_station`/`residual_transition`, which never see `x`
in any form except the two scalar arc-length values passed in. It therefore cannot and does not
capture:

- **AIC / `gamref` change** — `build_gamma` (`mfoil.py:609-667`) is not part of the residual
  loop at all; it is a separate solve (`np.linalg.solve(AIC, rhs)`) executed once per inviscid
  update. A node-coordinate perturbation changes every entry of `AIC` (via `panel_linvortex_stream`
  → `panel_info` → `atan2`), hence `gamref`, hence `ueinv` used in the `R_ue` mass-balance row
  (§1.3). None of this is differentiated anywhere in `R_x`.
- **`ue_m` change** — `calc_ue_m` (`mfoil.py:1472-1623`) is likewise a standalone geometric
  build, not part of `residual_station`. `ue_m` appears explicitly in `R_V`'s ue-block
  (`mfoil.py:1980-1981`) and mfoil has **no stored linearization of `ue_m` w.r.t. anything** —
  it is treated as a constant within one Newton iteration and only rebuilt wholesale when
  `rebuild_isol`/`calc_ue_m` is called again (see §7).
- **Stagnation-point *location* as a function of geometry** (as opposed to as a function of
  `ue`, which *is* captured, see above) — `stagpoint_find` depends on `gam`, which depends on
  `AIC`, which depends on `x`. Not differentiated.
- **Wake shape** — `build_wake`'s predictor-corrector trajectory is a numerical integration with
  no adjoint/tangent stored; a geometry change re-walks the whole wake.
- **Panel length/orientation terms inside `panel_info`** feed `cfxt`/`cDixt`/etc. only insofar as
  those functions take the *xi argument* — the underlying dependence of `d`, `theta1`, `theta2`
  (panel-local geometry) on node coordinates is a different, unrelated derivative not captured
  by `R_x` at all (those quantities don't appear in `residual_station`'s signature).

### 3.3 Conclusion

`dR/dA = R_x · dx/dA` (with `dx/dA` the CST design Jacobian) would silently omit the AIC/
inviscid-coupling sensitivity, the `ue_m` sensitivity, the stagnation/wake sensitivity — i.e.
everything except the arc-length-redistribution effect. Since the dossier's own framing (§7.6)
identifies `∂R/∂A = (∂R/∂x)(∂x/∂A)` as "the whole point of the hypothesis," an incomplete
`R_x`-only chain rule would silently corrupt exactly the derivative block the paper's claims rest
on. **Do not use the analytic-`R_x` shortcut for T5.** Use the dossier's fallback: perturb `A`
directly (not node coordinates), rebuild panels + AIC + `ue_m` (+ wake, + stagnation) per
perturbation, and finite-difference the **full augmented residual** (`R` from `build_glob_sys`
concatenated with the `R_ue` mass-balance row from `solve_glob`) at fixed `U`. This is ~`n_A`
(≈20) columns, each one residual **evaluation** (`build_glob_sys` + the `R_ue` formula), not a
flow solve — cheap relative to one converged Newton solve, exactly as the dossier estimates.
Complex-step for this FD is addressed next (§4) — and turns out **not** to be available for this
particular path, which changes the dossier's "if complex-safe, use complex-step" recommendation
into "use real central differences."

---

## 4. KEY QUESTION B — is the residual-assembly path complex-step safe?

**Short answer: partially, and the parts that fail are exactly the geometry-dependent parts
identified in §3 as missing from `R_x` — meaning complex-step cannot rescue the very derivative
block that most needs rescuing. Real (central) finite differences over `A` are the correct T5
strategy, not complex-step.**

Two independent findings, both empirically verified (not just static analysis) by running
`.venv/bin/python` against a converged viscous solve (NACA 2412, 80 panels, `alpha=3°`,
`Re=2e5`) and complex-perturbing inputs by `1e-30j`:

### 4.1 `residual_station`/`residual_transition` alone (fixed panels, real `U`): complex-step-safe

With node geometry (hence `AIC`, `ue_m`, panel structure) held fixed and only the two-point `xi`
argument complex-perturbed, `residual_station` runs clean and reproduces the analytic `R_x`
exactly:

```
complex-step over x OK, R dtype complex128
complex-step dR/dx1 = [18.05345897 -2.66559715  0.        ]
analytic  R_x[:,0]  = [18.05345897-1.9e-29j -2.66559715-1.1e-29j  0.+0.j]   # matches to float64 eps
```

The many `if (Hk < threshold): ...` branch-selection comparisons throughout the closure
functions (`get_Hk` `mfoil.py:2989-2990`, `get_cteq` `mfoil.py:3017/3042/3045/3048`, `get_Hss`
`mfoil.py:3074-3075`, `get_cf` `mfoil.py:3370/3374/3383`, `get_cfxt`, `get_cDi*`
`mfoil.py:3432/3531/3698-3699/3728`, `get_de` `mfoil.py:3284`, etc.) turned out **not** to be a
problem even when `U` itself is complex-perturbed: NumPy 2.5.1's `complex128 < float` comparison
silently compares the **real part only** (verified directly:
`np.complex128(3+1e-30j) < 5.5 -> True`, no warning, no error) — so branch selection is correct
(the branch a real-valued Newton iterate would take), and the subsequent formula still carries
the full complex value through. This matches the dossier's stated distinction exactly: "branch
selection on real quantities is complex-step tolerable" — confirmed true here **for the branches
that select on `Hk`, `Ret`, etc., because the imaginary perturbation is always many orders below
the branch threshold's resolution and the comparison silently degrades to `.real`.**
`complex-step over U OK` was also verified directly for a single-station `residual_station` call
with no active transition at that station.

**Caveat, also verified**: `residual_transition` (`mfoil.py:2623-2721`, used whenever two
adjacent nodes on a surface straddle laminar→turbulent transition, `tran` flag at
`mfoil.py:2125`) contains an explicit self-check at `mfoil.py:2713`:

```python
if (any(np.imag(R) != 0)): raise ValueError('imaginary transition residual')
```

This guard exists because the function internally runs a **sub-Newton iteration to locate the
transition point `xt`** (`mfoil.py:2652-2665`) using `abs(dxt)`, `abs(Rxt)` for step-limiting and
convergence — `abs()` on a complex number returns the *modulus*, which is not complex-
differentiable (not holomorphic), so once `xt` itself is complex (inevitable if the input `xi`
arguments are complex-perturbed), the `abs()`-based step control corrupts the "clean" complex-
step derivative and the internal consistency check at line 2713 will legitimately fire. **Any
Newton station that currently has a laminar→turbulent transition between its two bracketing
nodes will make a naive complex-step evaluation of the full residual raise `ValueError`.** In
the test airfoil this is common — `[sum(turb) per surface] = [0, 14, 19]` with the upper surface
showing an active transition boundary (`turb[:-1] ^ turb[1:]).any() == True` on surface 1).
Working around this would require monkeypatching `residual_transition` (or its internal `abs()`
calls) from the adapter — out of scope for T1, flagged as a T5 trap.

### 4.2 The geometry-dependent operators (`build_gamma`, `calc_ue_m`, `build_wake`): NOT
complex-step-safe — hard `TypeError`, verified

This is the decisive finding. Complex-perturbing a single node coordinate
(`M.foil.x[1, 10] += 1j*1e-30`, geometry held complex) and calling the geometry-rebuild sequence
that T5 needs after every `A`-perturbation:

```
build_gamma(m, alpha)  -> TypeError: ufunc 'arctan2' not supported for the input types, ...
build_wake(m)          -> TypeError: ufunc 'arctan2' not supported for the input types, ...
calc_ue_m(m)           -> TypeError: ufunc 'arctan2' not supported for the input types, ...
stagpoint_find(m)      -> OK (only uses gam/s, no direct atan2 call)
build_glob_sys(m)      -> OK but silently discarded the complex perturbation upstream
                           (ComplexWarning: "Casting complex values to real discards the
                           imaginary part" fired 3 times, e.g. mfoil.py:749, mfoil.py:2114)
```

Root cause: `panel_info` (`mfoil.py:885-919`, used by every `panel_linvortex_*`/
`panel_constsource_*`/`panel_linsource_*` function, i.e. every panel-influence computation in
`build_gamma` and `calc_ue_m`, and by `inviscid_velocity` used in `build_wake`) computes panel
angles via

```python
# mfoil.py:916-917
theta1 = atan2(z, x)
theta2 = atan2(z, x-d)
```

where `atan2` (`mfoil.py:260-261`) is a bare wrapper around `np.arctan2`. **`np.arctan2` has no
complex-argument overload at all** (unlike `log`, `sqrt`, `exp`, which extend holomorphically and
are what make complex-step normally work) — NumPy raises `TypeError` immediately rather than
silently truncating. There is no way around this without altering how `panel_info`'s angles are
computed (e.g. replacing `atan2(z,x)` with a complex-analytic equivalent such as
`-1j*log((x + 1j*z)/sqrt(x**2+z**2))`), which would mean shimming/monkeypatching the module-level
`atan2` name from the adapter (technically possible, in the same spirit as the ADR-0001 `Glob`
shim, since `atan2` is a free function resolved by name at call time and reassignable via
`mfoil_module().atan2 = complex_safe_atan2` without touching the vendor file) — but this is a
nontrivial, unverified change and is called out here as a *possible* future ADR, not something
implemented for T1.

### 4.3 Conclusion for T5

- The **only** path that is verified complex-step-safe is the arc-length (`xi`) sensitivity
  already captured analytically by `M.glob.R_x` — i.e. complex-step buys nothing here that
  isn't already available for free.
- The geometry-dependent operators that `R_x` is missing (§3.2) — `AIC`/`gamref`, `ue_m`, wake
  shape, stagnation-via-`gam` — are exactly the ones that fail complex-step outright, due to
  `np.arctan2` in `panel_info` (`mfoil.py:916-917`), a hard blocker with no workaround short of
  patching the vendored trig call.
- **Recommendation: use real (central) finite differences with respect to `A`** for the
  geometry-dependent Jacobian block, evaluating the full augmented residual
  (`build_glob_sys` + `R_ue` formula, §1.3) at each of the ~`2*n_A` perturbations (central) or
  `n_A+1` (forward), at fixed converged `U` and fixed `M.vsol.turb`. This sidesteps both
  problems found above (the `atan2` blocker and the `residual_transition` imaginary-residual
  guard) since real perturbations never produce complex intermediates. Step size should be
  chosen by the standard forward/central-FD noise-vs-truncation trade-off (`~sqrt(eps)` /
  `~eps^(1/3)` scaled by the CST coefficient magnitude) since machine-precision complex-step
  accuracy is not achievable here — this should be validated empirically once T5 is built (T6
  diagnostics), not assumed.

---

## 5. Cp extraction

`M.post.cp` is set in `calc_force` (`mfoil.py:400-482`), not in `get_distributions`:

```python
# mfoil.py:416-418
ue = M.glob.U[3,:] if M.oper.viscous else get_ueinv(M)
cp, cp_ue = get_cp(ue, M.param); M.post.cp = cp
M.post.cpi, cpi_ue = get_cp(get_ueinv(M), M.param)     # inviscid cp, for reference/plotting
```

`get_cp` (`mfoil.py:3121-3138`) is a **pure, pointwise function of speed**, with an optional
Karman-Tsien compressibility correction:

```python
def get_cp(u, param):
    Vinf = param.Vinf
    cp = 1 - (u/Vinf)**2
    cp_u = -2*u/Vinf**2
    if param.Minf > 0:
        l, b = param.KTl, param.KTb
        den = b + 0.5*l*(1+b)*cp; den_cp = 0.5*l*(1+b)
        cp /= den; cp_u *= (1 - cp*den_cp)/den
    return cp, cp_u
```

`u` and the returned `cp_u` are vectors — `get_cp` is called once on the whole `ue` array and
returns `cp[j]`, `cp_u[j]` per node `j` in one shot; no compressibility correction is active
unless `M.oper.Ma > 0` is set (`M.param.Minf` populated from `M.oper.Ma` in `init_thermo`,
`mfoil.py:1626+`, not reproduced here).

**Implication for T5's target-Cp residual `T(U) - Cp_target`**: since `cp[j] = f(ue[j])` only —
`ue` being row 3 of `U` at node `j` — the Jacobian `dT/dU` is exactly the "near-selection matrix"
the dossier anticipates: zero everywhere except the `ue` column of each target node's row, scaled
by `cp_u[j]` (the *compressible* `dcp/du`, i.e. `get_cp`'s second return value evaluated at the
target nodes, not a naive `-2u/Vinf^2` if `Ma>0`). Concretely, for `M` target stations at node
indices `{j_1..j_M}`:

```
T(U)_k    = cp[j_k] - Cp_target_k             (k = 1..M)
dT/dU     : row k has a single nonzero entry at column (4*j_k + 3)   # ue is row index 3 of 4
            value = cp_u[j_k]                 (from get_cp's second output)
```

Build this by calling `get_cp(M.glob.U[3, target_idx], M.param)` directly rather than
re-deriving the Karman-Tsien correction — cheap, exact, and automatically correct for the `Ma>0`
case.

---

## 6. Forced transition

**mfoil has no forced-trip / `xtr` API.** Grepped exhaustively (`xstrip`, `forced`, `xtr\b`) —
nothing. Transition is **always** natural, governed by the amplification-factor (`e^n`) method:

- `M.param.ncrit` (default 9.0, `mfoil.py:148`) — the single global critical-amplification-factor
  knob, applied identically on both surfaces.
- Per-node state: `M.vsol.turb` (`int` array, 0=laminar/1=turbulent, one entry per `Nsys` node,
  allocated in `init_boundary_layer`, `mfoil.py:2326`).
- Transition **detection** happens in two different code paths:
  - `march_amplification` (`mfoil.py:2561-2619`) — marches the amplification-factor ODE forward
    from the stagnation point on each surface during BL initialization/re-initialization
    (`init_boundary_layer`) and after Newton state updates (`update_transition`,
    `mfoil.py:2507-2560`, which calls `march_amplification` and re-flags `M.vsol.turb` when the
    marched `sa` crosses `param.ncrit`, `mfoil.py:2608`).
  - Inside the Newton residual assembly itself, `build_glob_sys` detects a `tran` station simply
    from **the current, frozen `M.vsol.turb` array** (`tran = turb[i-1] ^ turb[i]`,
    `mfoil.py:2125`) — i.e. transition location is *not* re-solved inside every residual
    evaluation, only inside `update_transition`, which runs once per outer Newton iteration
    (`solve_coupled`, `mfoil.py:1772-1833`, calls `update_transition` at `mfoil.py:1830`, *after*
    `update_state`).

**Cleanest non-invasive way to pin transition from the adapter** (no vendor edit): after
`init_boundary_layer`/one warm solve, directly overwrite `M.vsol.turb` to the desired 0/1 pattern
at the node indices corresponding to the desired trip location(s), **then prevent
`update_transition` from re-deriving it** on subsequent Newton iterations. Since
`update_transition` is a free module-level function (like `atan2`), it can be shimmed from the
adapter the same way ADR-0001 shims `Glob.realloc`:

```python
_mfoil_mod.update_transition = lambda M: None   # freeze M.vsol.turb at its current pattern
```

This is a legitimate, non-invasive, ADR-0001-style override (reassigning a module-level name from
outside the vendor file) and should be proposed as its own ADR if/when forced transition is
needed — not implemented here, since T1 is documentation-only. A softer alternative that avoids
monkeypatching entirely: set `M.param.ncrit` very large (transition never triggers naturally,
fully laminar) or very small/negative-effective (transition triggers immediately at the
stagnation-adjacent node) — but this only gives coarse "fully laminar" / "trip at leading edge"
control, not an arbitrary pinned `x/c`.

---

## 7. Solve call order

### 7.1 Top-level (`M.solve()`, `mfoil.py:216-221`)

```
if M.oper.viscous: solve_viscous(M)
else:               solve_inviscid(M)
```

### 7.2 `solve_viscous` (`mfoil.py:1747-1767`) — the full cold-start sequence

```
solve_inviscid(M)        # -> build_gamma (AIC, gamref, gam)
M.oper.viscous = True
init_thermo(M)
build_wake(M)             # needs gam
stagpoint_find(M)         # needs gam
identify_surfaces(M)      # needs Istag -> vsol.Is
set_wake_gap(M)
calc_ue_m(M)              # needs foil.x, wake.x, AIC, gam  (the expensive geometry-dependent build)
init_boundary_layer(M)    # needs ue_m indirectly via ueinv; sets glob.Nsys, glob.U, vsol.turb
stagpoint_move(M)         # viscous-informed stagnation refinement
solve_coupled(M)          # the Newton loop
calc_force(M)
get_distributions(M)
```

### 7.3 `solve_coupled` (`mfoil.py:1772-1833`) — the Newton loop itself

```python
M.glob.realloc = True                      # force sparse reallocation on iter 0
for iNewton in range(niglob):
    build_glob_sys(M)                      # R, R_U, R_x   (§1.2/§1.3, §3)
    calc_force(M)                          # Cp, cl, cm  (needed for cl-constrained mode + logging)
    if norm(R) < rtol: converged; break
    solve_glob(M)                          # assembles augmented R_V (4Nsys[+1]^2), solves for dU, dalpha
    update_state(M)                        # under-relaxed update + Hk/ctau repair (§1.5);
                                            # calls rebuild_isol(M) if alpha changed
    M.glob.realloc = False
    stagpoint_move(M)                      # NOT a full rebuild_isol — just Istag/xi refinement
    update_transition(M)                   # marches amplification, may flip vsol.turb entries
```

### 7.4 What must be re-called after a **geometry** change mid-Newton (the T5 hook)

None of the four steps inside the Newton loop above (`build_glob_sys`, `solve_glob`,
`update_state`, `stagpoint_move`/`update_transition`) rebuild panels, AIC, or `ue_m` — they all
assume **fixed geometry** within an outer Newton iteration and only react to *state* changes
(`ue`, `alpha`). This is the load-bearing fact for T5's extended Newton system: **mfoil itself
never needs a "geometry changed mid-Newton" hook, because in stock mfoil geometry never changes
mid-Newton.** T5 introduces that need. Based on `rebuild_isol` (`mfoil.py:812-830`, mfoil's own
handler for the *one* case where it does need to react to a change upstream of the flow state —
an `alpha` change) and the cold-start sequence above, the **minimal correct rebuild sequence**
after `M.geom.xpoint`/`M.foil.x` changes (i.e. after an `A`-update in T5) is:

```python
make_panels(M, npanel, list(M.foil.s))   # re-spline to new geometry, same N/s-distribution (§2.1)
build_gamma(M, M.oper.alpha)             # new AIC, gamref, gam           (mfoil.py:609-667)
build_wake(M)                            # new wake trajectory, uewi      (mfoil.py:723-778)
stagpoint_find(M)                        # new Istag, xi                  (mfoil.py:781-808)
identify_surfaces(M)                     # new vsol.Is (index ranges only; unaffected if N fixed)
set_wake_gap(M)                          # TE-blunt wake gap, geometry-dependent (mfoil.py:1666-1684)
calc_ue_m(M)                             # new ue_m, sigma_m — THE expensive step (mfoil.py:1472-1623)
```

This mirrors `rebuild_isol`'s `redowake` branch (`mfoil.py:827-830`:
`build_wake; identify_surfaces; calc_ue_m`) plus the paneling/AIC steps `rebuild_isol` doesn't
need (because it only handles `alpha` changes, where `AIC`/`gamref` don't change — only their
linear combination `gam` does, `mfoil.py:824`). **`Nsys` and `M.glob.U`/`M.vsol.turb` are left
untouched** by this sequence — the flow state carries over from the previous Newton iterate,
which is the desired behavior for a monolithic Newton step (state and geometry march together,
not geometry-then-reinitialize-BL).

**Cost note**: `calc_ue_m` is the dominant cost in this sequence — it is `O(N*Nw)` dense-matrix
work (`Cgam`, `B`, `Csig` are all explicitly dense `numpy` arrays, `mfoil.py:1490, 1496, 1526`)
plus one `N x N` dense linear solve (`Bp = -solve(AIC, B)`, `mfoil.py:1522`). At `N~80, Nw~20`
this is fast (milliseconds), but it is **not sparse** and will not scale as gracefully as the
rest of the Newton system if panel counts grow — worth profiling once T5's per-iteration column
count (`~n_A` FD evaluations, each needing this rebuild) is known (T6).

---

## T5 implications

**Derivative strategy.** `M.glob.R_x` is real and directly usable, but it only covers the
arc-length-redistribution term inside `residual_station`/`residual_transition` (§3.1) — it is
silent on the AIC/`gamref`, `ue_m`, and wake/stagnation sensitivities that dominate the physical
picture (§3.2). Complex-step cannot fill that gap either: the geometry-dependent operators
(`build_gamma`, `calc_ue_m`, `build_wake`) hit a hard `np.arctan2`/complex `TypeError` inside
`panel_info` (§4.2), and even the residual-station path alone is only complex-step-safe when no
active laminar→turbulent transition station is present (§4.1, `residual_transition`'s explicit
`ValueError` guard at `mfoil.py:2713`). **Use real (central) finite differences with respect to
`A`** (~`2*n_A` full-residual evaluations per Newton iteration, each = one geometry rebuild
(§7.4) + one `build_glob_sys` + the `R_ue` mass-balance formula, at fixed `U` and fixed
`vsol.turb`) to assemble `∂R/∂A` (all 4·Nsys rows, since `A` affects both `R` and the `R_ue`
row via `ueinv`/`ue_m`). This is exactly the dossier's stated fallback, upgraded from "likely
needed" to "empirically confirmed needed."

**Geometry-update procedure per Newton iteration**: the 7-line sequence in §7.4
(`make_panels` with `stgt` as a **list**, then `build_gamma`, `build_wake`, `stagpoint_find`,
`identify_surfaces`, `set_wake_gap`, `calc_ue_m`) — this is the concrete "geometry update hook"
the dossier asks for. It must be invoked once for the baseline `A` and once more per FD
perturbation column.

**Traps to design around:**

1. **`spline_curvature`'s `stgt == None` bug** (§2.1) — always pass `stgt` as a `list`, never an
   `ndarray`, or every re-panel call after the first will crash with a `ValueError` about
   ambiguous array truth values.
2. **`set_coords` is unusable as shipped** (`X.shape(1)` typo, §2.1) — never call
   `mfoil(coords=...)` or `set_coords` from the adapter; write `M.geom.xpoint`/`npoint`/`chord`
   directly.
3. **Fixing `stgt` fixes node *count* and *s-distribution*, not node position** — this is the
   correct behavior (needed to keep `Nsys` constant across the Newton system), but it means the
   physical arclength fraction, not a CST-`psi` fraction, is what's held fixed; if T2's `psi`
   sampling grid and mfoil's re-splined `s`-grid diverge significantly at high curvature (LE),
   revisit whether `stgt` should instead be derived fresh from the CST `psi` grid every iteration
   (trading node-position stability for psi-alignment) — flag as an open design choice, not
   resolved here.
4. **`residual_transition`'s hard-coded imaginary-residual guard** (`mfoil.py:2713`) blocks any
   future attempt to complex-step *through* a transition station, even for parts of the system
   where it would otherwise work (e.g. if someone tries complex-step on `∂R/∂U` alone, which is
   not needed for T5 since `R_U` is already analytic, but is worth remembering if T6 diagnostics
   ever want a complex-step cross-check of `R_U`).
5. **Stagnation index (`Istag`) can jump** between adjacent airfoil nodes as `A` changes (it is
   found by a sign-change search over `gam`, `mfoil.py:794-796`) — a large-enough `A` perturbation
   could shift `Istag` by more than one node, which changes `M.vsol.Is[0]`/`Is[1]` (the surface
   partitions) discretely. This is not a smooth function of `A` at that boundary; keep FD step
   sizes small enough that this doesn't happen within a single differencing stencil, and consider
   asserting `Istag` is unchanged across all FD columns in T6 diagnostics as a sanity check.
6. **Wake rebuild cost** (§7.4 cost note) — `calc_ue_m` is `O(N·Nw)` dense + one dense `N×N`
   solve, repeated `~2*n_A` times per Newton iteration for central FD. At `N≈80-200`, `Nw≈20-40`
   this is fast, but it is the clear hotspot to profile first if T5 turns out slower than
   expected; a forward-difference (`n_A+1` evals) halves this cost at the price of first-order
   truncation error, worth an explicit ablation (§7.9 of the dossier already asks for FD-order
   ablations — this is the concrete cost knob that motivates it).
7. **`Nw = ceil(N/10 + 10*wakelen)`** (`mfoil.py:740`) depends only on `N` (fixed by the `stgt`
   discipline above) and `M.geom.wakelen` (a solver parameter, not touched by CST) — so `Nw`,
   and hence `Nsys`, is guaranteed constant across all FD columns and Newton iterations as long
   as `stgt` keeps `N` fixed. Verify this invariant holds in T6 diagnostics rather than assuming
   it silently.
