# SPEC — CINS Engineering Specification

Status: binding. Source of truth for math and task gates. Derived from the research dossier
[`docs/CST_MISES_Monolithic_Inverse_Design.md`](CST_MISES_Monolithic_Inverse_Design.md)
(§3 CST math, §4 failure modes, §7 Stage-1 build spec, Appendix B task checklist).
Config keys cross-referenced live in [`configs/default.yaml`](../configs/default.yaml).
Gate-closure procedure is in [`docs/GATES.md`](GATES.md). Product/paper scope is in
[`docs/PRD.md`](PRD.md). Statistical protocol for T8/T9 is in
[`docs/STATS_PROTOCOL.md`](STATS_PROTOCOL.md). Math/sign conventions are additionally
binding in [`src/cins/CLAUDE.md`](../src/cins/CLAUDE.md); this document restates the
equations, that document owns the sign/ordering conventions.

---

## 1. Scope

Stage 1 only: isolated airfoil, mfoil (MIT-licensed, `vendor/mfoil/mfoil.py`, never edited —
access only via `src/cins/solver/mfoil_adapter.py`). Cascade (Stage 2) and MISES (Stage 3)
are out of scope for this document; see dossier §8–§9.

## 2. CST mathematics (dossier §3)

### 2.1 Surface parameterisation

ψ = x/c ∈ [0,1], ζ = z/c. Class function:

```
C_{N1}^{N2}(ψ) = ψ^{N1} (1 − ψ)^{N2}
```

Config: `cst.N1` (default 0.5), `cst.N2` (default 1.0) — round-nose, sharp-tail family.

Bernstein shape function of order n:

```
S_i(ψ) = K_i ψ^i (1 − ψ)^{n−i},     K_i = n! / (i!(n−i)!)
S_u(ψ) = Σ_i A_{u,i} S_i(ψ)          i = 0..n_upper   (config: cst.n_upper)
S_l(ψ) = Σ_i A_{l,i} S_i(ψ)          i = 0..n_lower   (config: cst.n_lower)
```

Surfaces:

```
ζ_upper(ψ) = C(ψ) S_u(ψ) + ψ ζ_{T,u}
ζ_lower(ψ) = C(ψ) S_l(ψ) + ψ ζ_{T,l}
```

with `ζ_{T,u} = +cst.te_gap/2`, `ζ_{T,l} = −cst.te_gap/2` (dossier §3.1; sign convention
binding in `src/cins/CLAUDE.md`).

`∂ζ/∂A_i = C(ψ) S_i(ψ)` is **design-independent** — a fixed basis matrix, assembled once,
cached, never recomputed inside a Newton loop (dossier §3.1, §7.3 T2 requirement).

### 2.2 Endpoint identities (linear equality constraints)

```
S(0) = A_0            = √(2 R_LE / c)              ⟹  A_0 = √(2 R_LE / c)
S(1) = A_n            = tan(β) + Δz_TE/c            ⟹  A_n = tan(β) + Δz_TE/c
```

β = boat-tail (TE wedge) angle. These identities make LE radius and TE wedge angle
**linear rows** in A rather than nonlinear geometric predicates (dossier §3.2, §1.5 table).

### 2.3 Leading-edge curvature

Near ψ → 0, ζ ≈ A_0 √ψ ⟹ R_LE = A_0² / 2. G² curvature continuity across the LE reduces to
`A_{u,0} = |A_{l,0}|`, i.e. under the stored-sign convention (`A_l,i < 0`), the row is
`A_{u,0} + A_{l,0} = 0` (dossier §3.3; sign binding in `src/cins/CLAUDE.md`).

### 2.4 Inscribed area — closed form (Beta function)

Per-surface area contribution:

```
∫_0^1 C(ψ) S_i(ψ) dψ = K_i ∫_0^1 ψ^{i+N1} (1−ψ)^{n−i+N2} dψ
                      = K_i · B(i + N1 + 1, n − i + N2 + 1)
```

For N1=0.5, N2=1.0: `K_i · B(i + 1.5, n − i + 2)`. Plus the TE term
`∫_0^1 ψ ζ_T dψ = ζ_T / 2`. Computed via `scipy.special.beta` — no numerical quadrature in
production rows (quadrature is the independent gate check only; `src/cins/CLAUDE.md`).

## 3. DOF accounting (dossier §4 FM-1, §7.6)

```
DOF = 2(n+1)        CST coefficients (n_A total, both sides)
      − 1            shared LE radius  (A_u0 = |A_l0|)
      − 1            TE thickness fixed
      + 3             scale / rotate / translate
      + 1             stagger or α

must equal   M + K     (targets + geometric equality constraints)
```

**Squareness condition**, asserted at construction and logged every run:

```
N_tot + M + K  =  N_tot + n_A + 1     ⟹     M + K = n_A + 1
```

Violation raises. This is the FM-1 guard: rank deficiency from a DOF-counting error can
present as "LE divergence" and must be ruled out first (dossier §4 FM-1, §7.9 ablation row).

| Term | Symbol | Where computed |
|---|---|---|
| CST coefficients (both sides) | `n_A = 2(n+1)` where `n = cst.n_upper = cst.n_lower` (or summed if unequal) | `cst/basis.py` |
| Shared LE radius row | 1 constraint | `cst/constraints.py: shared_le_radius_row` |
| TE thickness row | 1 constraint (or 0 if `cst.te_gap` fixed elsewhere) | `cst/constraints.py: te_wedge_row` |
| Scale/rotate/translate | 3 unknowns absorbed | Newton system, overall modes |
| Stagger / α | 1 unknown | Newton system, `α` block |
| Target stations | M | `T(U) − Cp_target = 0` |
| Geometric equalities | K | `G·A − b = 0` |

## 4. Extended Newton system (dossier §7.6, T5 — core deliverable)

**Unknowns:**

```
U   flow state          (N_tot)   — mfoil's augmented BL + panel/vorticity state
A   CST coefficients    (n_A)     — n_A = 2(n+1), less eliminations
α   angle of attack     (1)       — or stagger in cascade (out of Stage-1 scope)
```

**Equations:**

```
R(U; x(A)) = 0                flow residual             (N_tot)
T(U) − Cp_target = 0           at M target stations       (M)
G·A − b = 0                    geometric equalities       (K)
```

**Jacobian block structure:**

```
        ⎡ ∂R/∂U   ∂R/∂A   ∂R/∂α ⎤
   J =  ⎢ ∂T/∂U     0     ∂T/∂α ⎥
        ⎣   0     ∂G/∂A     0   ⎦
```

| Block | Content | Cost |
|---|---|---|
| `∂R/∂U` | mfoil's own analytic sparse Jacobian, reused unchanged | free (already assembled) |
| `∂R/∂A` | `(∂R/∂x)(∂x/∂A)`; `∂x/∂A = C(ψ)S_i(ψ)` cached design-independent matrix | see §5 derivative-mode decision tree |
| `∂R/∂α` | mfoil's existing α-sensitivity | free (already assembled) |
| `∂T/∂U` | Cp at a node as function of panel/edge-velocity unknowns — near-selection matrix | cheap |
| `∂T/∂α` | direct | cheap |
| `∂G/∂A = G` | constant | free |

Solve: sparse LU (`scipy.sparse.linalg.splu`). Reuse mfoil's under-relaxation ω logic on the
U block (θ, δ* limited to ≤50% decrease per step; Hk > Hk,min ≈ 1.00005 on airfoil, 1.02 in
wake). Apply a **separate, more permissive trust region on the A block**:
config `newton.a_trust_radius` (default 0.1, max |ΔA| per iteration).

## 5. Derivative-mode decision tree (dossier §7.2 T1, §7.6)

Config: `newton.derivative_mode` (`auto | analytic | complex_step | finite_difference`),
`newton.fd_step` (1e-6), `newton.cs_step` (1e-30).

```
1. Is ∂R/∂x available analytically from mfoil? (T1 introspection answers this — see
   docs/mfoil_internals.md)
   YES → use analytic chain rule: ∂R/∂A = (∂R/∂x)(∂x/∂A)   [derivative_mode = analytic]
   NO  → go to 2

2. Is the residual assembly path (not the update limiter) free of abs/max/min/comparison
   operators, i.e. complex-step safe? (T1 introspection answers this)
   YES → complex-step over A only (~n_A evaluations, NOT over node coordinates)
         [derivative_mode = complex_step, step = newton.cs_step]
   NO  → go to 3

3. Finite-difference over A only (~n_A residual evaluations per Newton step)
   [derivative_mode = finite_difference, step = newton.fd_step]
```

**Hard rule (never violate):** finite-difference or complex-step is always taken with
respect to **A** (≈20 columns), never with respect to node coordinates x (N_panel columns).
This is what keeps the flow-solve-count argument intact even when the analytic path is
unavailable (dossier §7.6).

`derivative_mode: auto` in config means: attempt step 1, fall back to step 2, fall back to
step 3, and log which path was actually used every run.

## 6. Diagnostics (dossier §7.7, T6 — build before needed)

| ID | Diagnostic | Discriminates |
|---|---|---|
| D-1 | Per-block residual norms ‖R‖, ‖T‖, ‖G‖ per iteration | Which block stalls |
| D-2 | `rank(J)`, `cond(J)`; rank of `[∂R/∂A; ∂G/∂A]` sub-block | **FM-1** rank deficiency masquerading as LE divergence |
| D-3 | `cond(GᵀG)` of the CST Gram matrix vs n | **FM-2** conditioning |
| D-4 | Row-norm profile of `∂R/∂A` vs chordwise station | **FM-3** LE singularity in Jacobian rows (expect spike at nose) |
| D-5 | Transition-location history per iteration | **FM-4** C⁰ closure chatter |
| D-6 | Newton convergence history, log‖R‖ vs iteration | Quadratic tail — the headline architectural claim |

D-6 is the paper's headline figure. D-2 saves the most debugging time — run it first whenever
convergence looks anomalous.

## 7. Task ladder T0–T9 and gate table

Tasks map 1:1 to dossier Appendix B. Every numeric threshold below is read from
`configs/default.yaml gates:` — this table is a cross-reference, not a second source of
truth; if a number here and in the config ever disagree, the config wins and this file has
a bug.

| Task | Deliverable | Gate criterion | Config key(s) |
|---|---|---|---|
| **T0** | Environment; mfoil baseline NACA 2412 viscous solve reproduces | cl within sanity band at α=2°, Re=1e6 | `gates.t0_cl_range` = `[0.1, 0.9]` |
| **T1** | Introspect mfoil globals → `docs/mfoil_internals.md`; determine dR/dx availability and complex-step safety | qualitative — findings documented, feeds §5 decision tree | — |
| **T2** | CST module: basis, surface, cached `dsurface_dA`, LEM, fit | fit RMS < threshold on NACA 2412 and sCO2 baseline; `cond(GᵀG)` vs n archived | `gates.t2_fit_rms_max` = `1.0e-3` (< 0.1% chord) |
| **T3** | Constraint rows: LE radius, shared LE radius (G²), TE wedge, area | `area_row` matches numerical quadrature | `gates.t3_area_quadrature_tol` = `1.0e-10` |
| **T4** | Linear pre-solve: M from mfoil panel operator, KKT solve, realisability metric | realisability metric implemented and thresholded | `presolve.realisability_threshold` = `0.05` |
| **T5** | Extended Newton system; assert M + K = n_A + 1 | assertion holds at construction, logged every run | derived from `cst.n_upper`, `cst.n_lower` |
| **T6** | Diagnostics D-1..D-6 | all six implemented and produce artifacts | — |
| **T7** | Falsifiable test: recover A* from self-generated Cp target (NACA 2412, sCO2 baseline) | `‖A − A*‖∞ < threshold`, ≤ max iterations, quadratic tail in D-6 | `gates.t7_a_recovery_inf_norm` = `1.0e-4`, `gates.t7_max_newton_iters` = `9` |
| **T8** | Ablations incl. nested-optimization control baseline | see `docs/STATS_PROTOCOL.md` (H1–H3, ablation matrix) | `experiment.seed` = `42` |
| **T9** | Stage 2 design review; cascade kernel decision | qualitative — design doc produced | — |

Solver settings shared across tasks: `paneling.npanel` (199), `paneling.spacing` (cosine),
`operating.*` (α, Re, Ma, viscous), `transition.mode` (forced during inverse iterations per
FM-4 mitigation, `transition.xtr_upper/lower` = 0.05), `newton.rtol` (1e-10),
`newton.max_iter` (50).

## 8. Failure-mode cross-reference

| ID | Name | Dossier ref | Primary diagnostic | Primary mitigation |
|---|---|---|---|---|
| FM-1 | DOF accounting / realisability | §4 FM-1 | D-2 | Explicit bookkeeping (§3 above), assertion at construction, T4 realisability metric |
| FM-2 | Bernstein conditioning | §4 FM-2 | D-3 | Keep n small (≤10–12/side); orthogonalise (CSTO) rather than regularise |
| FM-3 | LE singularity in Jacobian rows | §4 FM-3, §3.5 | D-4 | Row scaling/equilibration; `cst.le_treatment: prescribed` (fix first `cst.prescribed_le_fraction` of chord) recommended first |
| FM-4 | C⁰ viscous closure (transition) | §4 FM-4 | D-5 | `transition.mode: forced` during inverse iterations; release and verify in direct mode after convergence |

## 9. Do not

- Do not finite-difference or complex-step over node coordinates x — only over A (§5).
- Do not recompute `dsurface_dA` inside a Newton loop — it is design-independent (§2.1).
- Do not use numerical quadrature in production constraint rows — closed-form Beta function
  only; quadrature is a test-only cross-check (§2.4).
- Do not weaken a gate threshold in this document or in `configs/default.yaml gates:`
  without an ADR in `docs/adr/` (see `tests/CLAUDE.md`).
