# CST-Parameterised Monolithic Inverse Design for Airfoils and Turbine Cascades

**Research dossier and implementation handoff**

Version 1.0 — 3 August 2026
Author context: S. Sathish (PhD, sCO2 turbomachinery). Consolidates a literature survey, a solver-architecture hypothesis, and a build specification.

---

## 0. How to use this document

| If you are... | Read |
|---|---|
| An agent tasked with building the prototype | §1, §3, §4, §6, §7 — then start at §7.3 |
| Assessing novelty / writing the paper | §1, §2, §5, §9 |
| Choosing a solver or sorting out licensing | §6 |
| Planning the cascade extension | §8 |

Sections §7 and §8 are written as executable specifications. Everything an implementing agent needs to start Stage 1 is in §7; §8 is the design for Stage 2.

---

## 1. Objective and hypothesis

### 1.1 The problem

**Inverse airfoil/blade design**: given a target surface pressure or isentropic Mach distribution, recover the geometry that produces it. The forward (direct) problem — geometry in, pressure and loss out — is what MISES, XFOIL and mfoil normally do.

### 1.2 The hypothesis (precise statement)

> Inverse aerodynamic design need not be posed as an optimization problem. If the geometry is parameterised by a basis in which the surface is **linear in the design coefficients**, the geometric unknowns can be appended directly to the flow solver's global Newton system, producing a **square, determined nonlinear root-find** rather than an objective-function search. Class Shape Transformation (CST) is such a basis. Coupled to a Newton-based viscous/inviscid solver (MISES, or mfoil), it should therefore eliminate the outer optimization loop entirely.

### 1.3 What the hypothesis does and does not claim

| Claim | Status |
|---|---|
| "Inverse design need not be posed as optimization" | **Correct.** MISES's Modal-Inverse already works this way. |
| "CST is what makes it work where B-splines didn't" | **Correct, but for a specific reason** — see §1.5. Not primarily the LE singularity. |
| "No optimization at all is needed" | **Correct** if "optimization" = outer search loop with objective function. |
| "A closed-form / non-iterative solution results" | **Incorrect.** You still get a Newton root-find (5–15 iterations). The *linearised* thin-airfoil sub-problem is closed-form; the viscous transonic problem is not. |

The honest headline: **two to three orders of magnitude fewer flow solves, plus determinism and uniqueness** — not a closed form.

### 1.4 Origin

From the author's PhD (sCO2 axial turbine blading), CST + MISES + CAESES + Dakota/Kriging achieved a 17% profile-loss reduction over baseline, ~2% better than the best B-spline design. The thesis future-work section states the open problem verbatim:

> "Integration of Class Shape Transformation with MISES type flow solver would enhance inverse design capability which currently is mired in convergence issues because of singularity at the blade leading edge and non-smooth profile geometry."

### 1.5 Why CST specifically — the defensible version

**Do not claim "B-splines are non-analytic."** They are linear in their control points for a fixed knot vector, and a reviewer will say so. What was actually non-analytic in the CAESES setup was the *wrapper*:

- Control points displaced along **local normal-direction coordinate frames** attached to the baseline — a nonlinear, design-dependent map.
- **LE tangent-point angular displacement** to vary wedge angle — another nonlinear map.
- **Re-fitting / re-parameterisation** between iterations — breaks differentiability.
- A **curvature-monotonicity constraint** implemented as a discrete predicate — non-smooth, not a differentiable functional.

That stack is what forced surrogate-based search: the map from design variables to residual had kinks, so no Jacobian could be trusted, so sampling replaced differentiation.

CST collapses the stack. Since

```
ζ(ψ) = C(ψ) · Σᵢ Aᵢ Sᵢ(ψ) + ψ ζ_T
```

is **linear in A**, the geometric Jacobian block is

```
∂ζ/∂Aᵢ = C(ψ) · Sᵢ(ψ)
```

— a fixed, closed-form, **design-independent** basis function. It is assembled once, exact to machine precision, and never re-derived.

The second half is equally important: **constraints become linear algebraic rows rather than nonlinear predicates.**

| Constraint | Under CST | Under the B-spline wrapper |
|---|---|---|
| LE radius | `A₀ = √(2 R_LE/c)` — linear, exact | implicit, via tangent points |
| TE thickness | `ζ_T` term — linear | geometric post-check |
| Boat-tail / wedge angle | `Aₙ` — linear | nonlinear angular DV |
| Inscribed area | linear functional of **A**, Beta-function closed form (§3.4) | numerical, non-smooth |
| Curvature | rational function of **A**, differentiable | monotonicity predicate, non-smooth |

Constrained *optimization* becomes constrained *root-finding* — a bordered/KKT Newton system. Still square. Still a solve. **This is the publishable core of the argument.**

### 1.6 A convenient consequence

Because CST is linear in **A**, its **perturbation modes are identical to its basis functions**. A perturbation ΔA gives Δζ = C(ψ) Σ ΔAᵢ Sᵢ(ψ) — a fixed mode shape. CST therefore slots into MISES's Modal-Inverse `modes.xxx` mechanism natively, without BPREAD/BLDGEN surgery. This makes the eventual MISES prototype far cheaper than it appears.

---

## 2. Solver architecture: nested vs monolithic

**Nested (status quo, what the PhD did):**

```
Optimizer (Dakota + Kriging)
        ↓
Geometry rebuild (B-spline control points)
        ↓
MISES flow solve (fully converged)
        ↓
        └──────── repeat 10²–10³ times ────────┘
```

Properties: no convergence guarantee, local optima, design-space coverage limited by surrogate budget, cost dominated by converged flow solves.

**Monolithic (the hypothesis):**

```
┌─ One Newton system ────────────────────────────────┐
│  Flow unknowns          │  CST coefficients        │
│  (grid, density, BL)    │  (A_u, A_l as unknowns)  │
└────────────────────────────────────────────────────┘
        converges in ~5–15 Newton iterations
```

Properties: quadratic convergence near the root, unique answer if the target is realisable and the system square, no objective function, no line search, no DoE, no surrogate.

MISES's Modal-Inverse already implements this pattern — the mode amplitudes become Newton unknowns and target-pressure conditions become Newton equations. The novelty is not "add geometry unknowns to the Newton system" (Drela did that in 1986); it is:

1. Using a **complete, geometrically meaningful, analytic** basis so the modes are not heuristic bumps;
2. Constraints becoming **linear algebraic rows** rather than penalty terms or predicates;
3. Coefficient values being directly interpretable as manufacturing and mechanical constraints for turbine blades (LE radius, TE thickness, wedge angle, inscribed area).

---

## 3. CST mathematics — reference

### 3.1 Core formulation

Kulfan's representation, in the normalised form used in the thesis:

```
z/c = √(x/c) · (1 − x/c) · Σᵢ₌₀ᴺ [ Aᵢ (x/c)ⁱ ] + (x/c)(Δz_TE/c)
```

Reduced form, ψ = x/c, ζ = z/c:

```
ζ(ψ) = √ψ (1 − ψ) Σᵢ₌₀ᴺ Aᵢ ψⁱ + ψ ζ_T
```

**Class function** (general shape family):

```
C_{N1}^{N2}(ψ) = ψ^{N1} (1 − ψ)^{N2}
```

For a round-nose, sharp-tail airfoil: `N1 = 0.5`, `N2 = 1.0`.

**Shape function**, in Bernstein basis of order n:

```
Sᵢ(ψ) = Kᵢ ψⁱ (1 − ψ)^{n−i} ,    Kᵢ = n! / (i!(n−i)!)
S_u(ψ) = Σᵢ A_{u,i} Sᵢ(ψ)
S_l(ψ) = Σᵢ A_{l,i} Sᵢ(ψ)
```

**Surfaces:**

```
ζ_upper = C_{N1}^{N2}(ψ) S_u(ψ) + ψ Δζ_upper
ζ_lower = C_{N1}^{N2}(ψ) S_l(ψ) + ψ Δζ_lower
```

### 3.2 Geometric meaning of endpoint coefficients

```
S(0) = √(2 R_LE / c)     ⟹  A₀ = √(2 R_LE / c)
S(1) = tan β + Δz_TE/c   ⟹  Aₙ = tan β + Δz_TE/c
```

where β is the boat-tail angle. These two identities are what make LE radius and TE wedge angle **linear equality constraints**.

### 3.3 Leading-edge curvature (needed for continuity constraints)

Near ψ → 0, ζ ≈ A₀ √ψ, so ψ ≈ ζ²/A₀², i.e. the nose is an osculating parabola with

```
R_LE = A₀² / 2
```

**Consequence:** G² curvature continuity across the leading edge reduces to matching the leading coefficient magnitude, `A_{u,0} = |A_{l,0}|` — a single linear row. Continuity of the *derivative* of curvature involves `A_{u,1}` and `A_{l,1}`. This is a much cheaper constraint than it is under a spline representation, and is a concrete instance of §1.5.

### 3.4 Inscribed area — closed form (Beta function)

The area contribution of one surface:

```
∫₀¹ C(ψ) Sᵢ(ψ) dψ = Kᵢ ∫₀¹ ψ^{i+1/2} (1−ψ)^{n−i+1} dψ = Kᵢ · B(i + 3/2, n − i + 2)
```

plus the trailing-edge term `∫₀¹ ψ ζ_T dψ = ζ_T / 2`.

So inscribed area is a **linear functional of A with closed-form coefficients**. Compute once with `scipy.special.beta`; it becomes a constraint row. This is the same Beta-function machinery Joseph & Mohan (2021) use for the thin-airfoil integrals (§5.4), which is not a coincidence — both integrate Bernstein polynomials against the class function.

### 3.5 The leading-edge singularity — where it actually bites

The `√ψ` factor produces the desired blunt nose but is non-analytic at ψ = 0: dζ/dψ → ∞, curvature → ∞. Kulfan characterised the round-nose/sharp-tail body as continuous but non-analytic because of the infinite slope at the nose.

**Critical diagnostic point.** `∂ζ/∂Aᵢ` is perfectly finite at ψ → 0 (it tends to zero). The geometric **columns** are healthy. What blows up is the flow residual's sensitivity to geometry near the nose — surface normals, metric terms, and (in MISES) the m′–θ mapping all have unbounded derivatives there. A handful of **rows** near the stagnation point acquire enormous magnitude and destroy the condition number of the coupled matrix.

This is why the PhD saw *divergence* rather than slow convergence, and it dictates the fix: row scaling / equilibration, or removal of the pathological rows, not reformulation of the columns.

**Three fixes, increasing conservatism:**

1. **Kulfan LEM term** (added finite-nose-slope modification) + shared LE radius tying `A_{u,0}` to `A_{l,0}`, giving G⁰ plus a curvature-continuity row for G². Reference implementation exists in NeuralFoil (8 CST per side + LEM + TE thickness = 18 parameters).
2. **Masters' "unwrapped" square-root spline** centred at the leading edge, which expands the singular slopes into finite ones by construction.
3. **Mixed direct-inverse LE treatment** — geometrically *prescribe* the first 2–5% chord (nose radius, wedge angle: quantities already fixed by mechanical and cooling constraints in a turbine blade) and run inverse only aft of it. Classical mixed-inverse practice. Costs nothing you actually wanted to design, and removes the pathological rows entirely.

**Recommendation: try (3) first.** It is the cheapest test of the whole hypothesis and isolates the LE question from the architecture question.

### 3.6 CST variants worth knowing

| Variant | Reference | Purpose |
|---|---|---|
| Kulfan LEM | Kulfan, "Modification of CST Airfoil Representation Methodology" | Finite nose slope |
| Intuitive CST (iCST) | Zhu & Qin, *AIAA J* 52(1), 2014, pp. 17–25 | Maps CST DVs to PARSEC-like aerodynamic parameters via a transformation matrix |
| Local CST (l-CST) | Mura & Qin, AIAA 2017-0237 | Localised control |
| LE-region reformulation | Wang, Wang & Sun, *Proc. IMechE Part G*, 2021 | Rotated local frame so the LE is single-valued, avoiding the two-branch split |
| RBF shape function | Du, Lu, Guo, Zhou & Li, *J. Aircraft* 61(2), 2024 | Avoids high-order Bernstein ill-conditioning |
| CST-orthogonal (CSTO) | AIAA 2024-2140 | Orthogonalised basis, better conditioning |
| Exact Bezier equivalence | Marshall, AIAA 2013-3077 | CST ↔ Bezier conversion |
| Unwrapped square-root spline | Masters et al., *AIAA J* 55(5), 2017 | Finite LE slope |

---

## 4. The four failure modes — ranked

These are the things that will break the prototype. Ranked by expected severity, **not** by how obvious they are.

### FM-1: Degree-of-freedom accounting and realisability

**The hardest constraint, and the most likely to be misdiagnosed.**

You cannot prescribe an arbitrary Cp. Lighthill's integral constraints consume three degrees of freedom in incompressible inverse design — one for trailing-edge closure, two for free-stream consistency. Volpe & Melnik (1986) is essentially the transonic version of this well-posedness question.

So a target specified at M stations with 2(n+1) CST coefficients is **over-determined by three** unless absorbed. MISES's overall translation/scale/rotation modes are precisely the absorption mechanism.

**Bookkeeping that must be done explicitly:**

```
DOF = 2(n+1)                    CST coefficients
      − 1                       shared LE radius (A_u0 = |A_l0|)
      − 1                       TE thickness fixed
      + 3                       scale / rotate / translate
      + 1                       stagger or α

must equal   M  +  K            targets + geometric equality constraints
```

**Get this wrong and the system is singular or over-determined, and Newton will look like it is "diverging from the LE singularity" when it is actually rank-deficient.** There is good reason to suspect some of what the PhD observed was this, misattributed. Instrument for it (§7.7, D-2).

### FM-2: Bernstein conditioning

The Bernstein Gram matrix condition number grows roughly as 4ⁿ. At n = 10–12 per side you are at 10⁴–10⁶ before the flow solver contributes anything. In a monolithic Newton system that propagates directly into the coupled matrix.

**Tension with the hypothesis:** the natural fix is Tikhonov regularization, which turns a determined solve back into a least-squares — i.e. back into optimization. So the discipline is: **keep n small enough that the system stays well-conditioned as a solve.**

Masters et al. (2017) found 20–25 design variables cover the airfoil design space (across a test set of over 2000 aerofoils), i.e. roughly 10–12 per side. That is comfortably in solvable territory. If more resolution is needed, **orthogonalise the basis** (CSTO, or POD modes derived from the CST-spanned space) rather than regularise — orthogonalisation preserves the square-solve property.

### FM-3: LE singularity in the Jacobian rows

See §3.5. Rows, not columns. Fixes ranked there.

### FM-4: C⁰ viscous closure — the one nobody warns you about

MISES's and XFOIL's integral-BL transition closure is only **C⁰ in the design variables**. NeuralFoil documents that direct gradient-based optimization of XFOIL "invariably results in premature stopping at a local minimum" for exactly this reason. A Newton method needs a continuous Jacobian; a kink in the residual makes Newton chatter or stall.

**Mitigation: fix transition (forced trip) during the inverse iterations**, converge the shape, then release transition and verify in direct mode. Skipping this produces non-convergence that looks geometric but is thermodynamic.

Note that mfoil's author independently addressed a related issue: mfoil introduces "a more robust treatment of the amplification rate near transition" relative to XFOIL. Read that code before fighting this yourself.

---

## 5. Literature

### 5.1 CST foundation

- **Kulfan, B. M. & Bussoletti, J. E.** (2006). "'Fundamental' Parametric Geometry Representations for Aircraft Component Shapes." AIAA 2006-6948.
- **Kulfan, B. M.** (2007). "A Universal Parametric Geometry Representation Method — CST." AIAA 2007-0062.
- **Kulfan, B. M.** (2008). "Universal Parametric Geometry Representation Method." *Journal of Aircraft* 45(1), 142–158. DOI: [10.2514/1.29958](https://doi.org/10.2514/1.29958)
- **Kulfan, B. M.** "Modification of CST Airfoil Representation Methodology." [Academia.edu copy](https://www.academia.edu/121663665/Modification_of_CST_Airfoil_Representation_Methodology)

### 5.2 Parameterisation comparison and variants

- **Masters, D. A., Taylor, N. J., Rendall, T. C. S., Allen, C. B. & Poole, D. J.** (2017). "Geometric Comparison of Aerofoil Shape Parameterization Methods." *AIAA Journal* 55(5), 1575–1589. DOI: [10.2514/1.J054943](https://doi.org/10.2514/1.J054943) — *the* benchmark paper; 2000+ aerofoils, 20–25 DVs needed, SVD most efficient, CST best among analytic bases.
- **Zhu, F. & Qin, N.** (2014). "Intuitive Class/Shape Function Parameterization for Airfoils." *AIAA Journal* 52(1), 17–25.
- **Poole, D. J., Allen, C. B. & Rendall, T. C. S.** (2015). "Metric-Based Mathematical Derivation of Efficient Airfoil Design Variables." *AIAA Journal* 53(5).
- **Wang, S., Wang, C. & Sun, G.** (2021). "Modifications of class-shape transformation driven by aerodynamic concerns over leading-edge region." *Proc. IMechE Part G*. DOI: [10.1177/0954410020984570](https://doi.org/10.1177/0954410020984570)
- **Du, Lu, Guo, Zhou & Li** (2024). "RBF-modified CST." *Journal of Aircraft* 61(2).
- **Mura, G. & Qin, N.** (2017). "Local CST." AIAA 2017-0237.
- **Marshall, D. D.** (2013). "Creating Exact Bezier Representations of CST Shapes." AIAA 2013-3077.
- **Rajnarayan, D., Ning, A. & Mehr, J.** (2018). "Universal Airfoil Parametrization Using B-Splines." AIAA 2018-3949.
- **Lauer, C. & Ansell, P.** (2025). "A review of parameterization methods for airfoil design." *Progress in Aerospace Sciences* 158, 101140.
- **Samareh, J. A.** (2001). "Survey of Shape Parameterization Techniques." *AIAA Journal* 39(5).

### 5.3 Classical inverse design

- **Lighthill, M. J.** (1945). "A New Method of Two-Dimensional Aerodynamic Design." ARC R&M 2112. — foundational conformal-mapping inverse; source of the three integral constraints.
- **Woods, L. C.** (1952). ARC R&M 2845.
- **Strand, T.** (1973). Exact incompressible inverse design. *J. Aircraft*.
- **Volpe, G. & Melnik, R. E.** (1986). "The Design of Transonic Aerofoils by a Well-Posed Inverse Method." *Int. J. Numer. Meth. Engng* 22, 341–361.
- **Eppler, R. & Somers, D. M.** (1980). NASA TM-80210. / **Eppler, R.** (1990). *Airfoil Design and Data*, Springer.
- **Selig, M. S. & Maughmer, M. D.** (1992). "Multipoint Inverse Airfoil Design Method Based on Conformal Mapping" and "Generalized Multipoint Inverse Airfoil Design." *AIAA Journal* 30(5). — PROFOIL.
- **AGARD-R-780** (1990). *Inverse Methods in Airfoil Design for Aeronautical and Turbomachinery Applications.* — canonical reference volume.

### 5.4 The analytic kernel (thin-airfoil ↔ Bernstein)

- **Joseph, C. & Mohan, R.** (2021). "Closed-Form Expressions of Lift and Moment Coefficients for Generalized Camber Using Thin-Airfoil Theory." *AIAA Journal* 59(10), 4264–4270. DOI: [10.2514/1.J060859](https://doi.org/10.2514/1.J060859) — performs the thin-airfoil integrals with a Bernstein camber basis in closed form via the integral form of the Beta function; cites Kulfan's CST as motivation. **This is the analytic kernel for the linear pre-solve (§7.5).**
- **Souto Torres & Marques** (2024). *Meccanica*. DOI: [10.1007/s11012-024-01801-6](https://doi.org/10.1007/s11012-024-01801-6) — Gegenbauer-polynomial form of the loading coefficients; nonlinear geometric decomposition of thickness and camber.

### 5.5 MISES and the Newton-coupled family

- **Drela, M. & Giles, M. B.** (1987). "Viscous-Inviscid Analysis of Transonic and Low Reynolds Number Airfoils." *AIAA Journal* 25(10). — ISES; the global-Newton architecture.
- **Giles, M. B. & Drela, M.** (1987). *AIAA Journal* 25(9).
- **Giles, Drela & Thompson** (1985). AIAA 85-1530.
- **Drela, M.** (1986). MIT GTL Report 187 (PhD thesis).
- **Drela, M.** (1990). "Viscous and Inviscid Inverse Schemes Using Newton's Method." AGARD-R-780. — **the primary reference for Modal-Inverse and Mixed-Inverse formulations.**
- **Youngren, H.** (1991). MIT SM thesis / GT&PDL Report 203. — source of the Pcorr streamline-tension term that suppresses sawtooth grid modes; "really only required in inverse cases and in viscous cases with boundary layer separation."
- **Drela, M. & Youngren, H.** (1991). AIAA 91-2364.
- **Drela, M. & Youngren, H.** (2008). *A User's Guide to MISES 2.63.* [PDF](https://web.mit.edu/drela/Public/web/mises/mises.pdf)
- **Drela, M.** (1998). "Pros and Cons of Airfoil Optimization."

**MISES inverse modes (from the version notes and user guide):**

| Mode | Formulation |
|---|---|
| **Modal-Inverse** | Geometry perturbation = linear combination of fixed shape modes; **mode amplitudes added as unknowns to the global Newton system**, driven so computed surface speed matches target. Modes defined in `[modes].xxx`. Complemented by overall translation/scaling/rotation modes. |
| **Mixed-Inverse** | A surface *segment* left geometrically free with pressure specified there; endpoint closure/regularity constraints restore well-posedness. |
| **Parametric-Inverse** | Drives user-defined geometry parameters to a best fit to a target pressure distribution; explicitly designed to let MISES act as an inverse-design engine with **any** geometry-definition system. Geometry generated via black-box `BPREAD` / `BPWRIT` / `BLDGEN`; `SUBROUTINE BPCON` imposes geometric constraints (area, thickness, bending inertia). |

MISES 2.63 also dumps sensitivities of surface pressures, Hk and geometry with respect to specified parameters and geometry modes — i.e. **∂Cp/∂(mode amplitude) is already exposed.**

### 5.6 CST + inverse coupling that already exists (prior art)

- **Lane, K. A. & Marshall, D. D.** (2010). "Inverse Airfoil Design Utilizing CST Parameterization." AIAA 2010-1228. [ATTRIBUTION CORRECTED 2026-08-05: this entry previously named Morris, Allen & Rendall. Verified against the Cal Poly Digital Commons record and AIAA ARC; see docs/novelty-search.md.] — **nearest prior art.** Relates pressure residuals to required shape change (pressure-residual sign → normal-direction shape modification), with CST used as the *smoothing algorithm*. Solver-agnostic, subsonic and transonic. Note this is a weaker and structurally different construction from the monolithic proposal: CST smooths a correction, it is not an unknown in the Newton system.
- **CST + SU2 adjoint** — "Aerofoil Optimisation Using CST Parameterisation in SU2." Geometric sensitivities ∂(surface point)/∂Aᵢ for adjoint gradients.

**Negative result (verify before claiming novelty):** No published work couples the MISES *inverse* mode to CST, despite the Parametric-Inverse hook being explicitly built to accept it. This is from search, not an exhaustive library check. **Confirm via targeted AIAA and ASME Digital Collection searches before writing any novelty claim.**

### 5.7 Recent SOTA (2023–2026)

**Generative / ML inverse mapping (Cp → shape):**
- Yilmaz, E. & German, B. (2020). "Conditional Generative Adversarial Network Framework for Airfoil Inverse Design." AIAA AVIATION 2020-3185. DOI: [10.2514/6.2020-3185](https://doi.org/10.2514/6.2020-3185)
- Lei et al. (2021). WGAN + deep CNN multistage inverse for supercritical airfoils. *Aerospace Science and Technology* 119.
- **CDDPM** (2025). Classifier-free-guided conditional diffusion. *Structural and Multidisciplinary Optimization*. DOI: [10.1007/s00158-025-04111-x](https://doi.org/10.1007/s00158-025-04111-x); arXiv:2503.07056. Reports a 34.4% precision improvement over WGAN methods in airfoil generation.
- CcDPM (2024); DiffAirfoil (AIAA Aviation 2024); Airfoil-DDPM; latent-diffusion CST parameterisation, *Acta Aeronautica et Astronautica Sinica* 46(10), 2025.
- **LF-PINN inverse design using mfoil**: "Physics-Informed Machine Learning Using Low-Fidelity Flowfields for Inverse Airfoil Shape Design." *AIAA Journal*. DOI: [10.2514/1.J063570](https://doi.org/10.2514/1.J063570) — **read this before Stage 1**; it is the closest existing use of mfoil for inverse design.

**Differentiable CFD / adjoint in CST variables:**
- ML-for-adjoint-vector drag reduction in CST variables (arXiv:2012.15730).
- Differentiable full-potential CST optimization (arXiv:2605.17599), CST vector z ∈ ℝ¹².
- PINN state-space differentiable inverse in CST (arXiv:2401.07203).

**Turbomachinery-specific:**
- **Lavagnoli, S.** (2026). "Data-Driven Inverse Design of Turbine Blade Passages." *Energies* 19(12), 2796. DOI: [10.3390/en19122796](https://doi.org/10.3390/en19122796) — ~30,000 blade profiles generated via an automated optimization pipeline coupled with **MISES**; inlet flow angles −50° to 0°, outlet 50° to 75°, turning up to 125°. Benchmarks Kolmogorov–Arnold Networks against MLPs and GPR; ~0.1 s loading→geometry inference; mean outlet-angle error 0.086°, Mach RMS 0.004. Includes a **predicted-RMS feasibility proxy that flags ill-posed inverse targets** — the statistical analogue of the realisability check in §7.5.
- "Inverse Design of Compressor/Fan Blade Profiles Based on Conditional Invertible Neural Networks." ASME *J. Turbomach.* 147(10), 2025, 101014.
- "Parameterized-loading-driven inverse design for turbine blades via deep learning." *Energy*, 2023.
- Oliveira, Zhang & Zangeneh (2023). 3D inverse design of tandem-blade centrifugal compressors. ETC2023-270.
- Li, Meng, Zhou & Ji (2025). FFD-based adjoint compressor blade optimization. ASME *J. Turbomach.* 147(11), 111009.
- **Sathish, Kumar, Namburi, Swami, Fuetterer & Gopi** (2019). "Novel Approaches for sCO2 Axial Turbine Design." ASME GT2019. — the author's own CST+MISES 17% profile-loss result; direct lineage.

---

## 6. Solver landscape and licensing

### 6.1 MISES — gated but free for academia

- Project page: https://web.mit.edu/drela/Public/web/mises/
- User's guide (public): https://web.mit.edu/drela/Public/web/mises/mises.pdf
- MIT TLO listing: https://tlo.mit.edu/industry-entrepreneurs/available-technologies/mises-software-design-and-analysis-turbomachinery
- Non-commercial EULA: https://web.mit.edu/tlo/documents/MISES_EULA_noncommercial_2021_05.pdf

**Terms (as listed by MIT TLO):**

| Tier | Terms |
|---|---|
| Research / educational | **Free.** Signatories for academic institutions must be faculty. |
| Commercial | **$10,000** |
| Government contractor / agency | Contact TLO |

**Practical implication:** source is obtainable free *through a university*. Work performed at a commercial employer is commercial use. If pursued as personal research under a visiting or honorary academic affiliation, the free route opens. **Settle this before spending anything.**

**No open-source port of MISES exists** — not Python, not Julia, not anything. MSES (multi-element sibling) is under the same gate. Several turbomachinery design systems ship MISES *executables* without source, which is useless here since the whole point is to reach inside the Newton system.

### 6.2 mfoil — the Stage 1 testbed

- Code and documentation: http://www-personal.umich.edu/~kfid/codes.html (also https://websites.umich.edu/~kfid/codes/mfoil/mfoil.pdf)
- Paper PDF: https://public.websites.umich.edu/~kfid/MYPUBS/Fidkowski_2023_mfoil.pdf
- **Fidkowski, K. J.** (2022). "A Coupled Inviscid–Viscous Airfoil Analysis Solver, Revisited." *AIAA Journal* 60(5), 2961–2971. DOI: [10.2514/1.J061341](https://doi.org/10.2514/1.J061341)
- **Licence: MIT** — virtually no restrictions on usage or modification.

**Why it is near-ideal:**

1. Single-file MATLAB **and Python** class. Same physical models as XFOIL, with some differences in the coupled solver.
2. **Coupled inviscid panel and viscous integral boundary-layer discretisation solved with a Newton–Raphson solver using analytical derivatives and sparse-matrix Jacobian storage.** You need to append columns and rows to a Jacobian; mfoil hands you that Jacobian in Python.
3. **Access, via modular structures, to all solution and post-processing variables** — no file-based black-box coupling.
4. Directly relevant modifications over XFOIL: an augmented-state coupled solver for more control in limiting the state update, **a new stagnation-point formulation to reduce leading-edge oscillations in the boundary-layer variables**, and a more robust treatment of the amplification rate near transition. Someone has already fought the stagnation-region conditioning battle in code you can read (relevant to FM-3 and FM-4).
5. Confirms the initialisation point: the coupled solver "can fail when the initial guess, which comes from an uncoupled initialization, is not very good" — precisely why the analytic pre-solve of §7.5 matters.

**Limitations (real, but do not block Stage 1):** isolated airfoil only — no cascade periodicity, no pitch/stagger, no AVDR streamtube contraction; incompressible with a nonlinear Kármán–Tsien compressibility correction, so subcritical only.

The hypothesis is a claim about **solver architecture, not turbine aerodynamics**. Whether appending CST columns to a Newton system yields a square, well-conditioned, quadratically convergent solve is answered just as well on an isolated airfoil — for free, in Python. All four failure modes of §4 appear in mfoil.

### 6.3 Other options and why they are not Stage 1

| Solver | Licence | Verdict |
|---|---|---|
| **XFOIL** 6.99 | GPL, Fortran. https://web.mit.edu/drela/Public/web/xfoil/ | Has MDES (complex-mapping inverse) and GDES/MODI (mixed-inverse), so the machinery exists — but instrumenting 1980s Fortran with COMMON blocks to expose and extend the Newton matrix is strictly more work than mfoil's Python for no additional payoff. |
| **MULTALL** (Denton) | Free FORTRAN77. https://sites.google.com/site/multallopen/home · https://github.com/paopaoai11/Multall-open-18.3 · DOI [10.1115/1.4037819](https://doi.org/10.1115/1.4037819) | Genuinely open, includes Q3D blade-to-blade on a prescribed stream surface. **But it is a time-marching finite-volume solver — no global Newton, no Jacobian, nothing to append unknowns to.** Cannot host the hypothesis. Use as an *independent verifier* of geometry produced by the inverse. |
| **SU2** | LGPL | Mature discrete adjoint, existing CST integration. But adjoint target-Cp matching *is* optimization — the thing the hypothesis avoids. Makes a good **control experiment**, not a test. |
| **T-Blade3** | Open source, U. Cincinnati | Differentiated blade generator with existing OpenMDAO–MISES coupling scripts. Useful as a geometry-generation reference for Stage 3. |
| **mfoil variants** | — | `mfoil.py` is the target. Vibefoil (JS XFOIL port) and Xfoil-for-MATLAB exist but offer nothing extra here. |

### 6.4 The gap worth naming

**There is no open-source, Newton-coupled, cascade blade-to-blade solver.** MISES is gated; MULTALL is time-marching; mfoil is isolated-airfoil. If the CST-monolithic-inverse idea works on mfoil, the natural second contribution is that solver: mfoil's architecture + cascade periodicity + a CST-native inverse mode, MIT-licensed. That would serve a field that has been waiting on a $10k licence since 1994.

---

## 7. STAGE 1 — Build specification (mfoil, isolated airfoil)

**Goal:** demonstrate that a monolithic CST-Newton inverse converges, and identify which of FM-1…FM-4 dominates.

**Deliverable:** a Python package that takes a target Cp distribution and returns CST coefficients, without any optimizer.

**Estimated effort:** T1–T4 are 1–2 days; T5–T7 are the research content.

### 7.1 Environment

```bash
python -m venv .venv && source .venv/bin/activate
pip install numpy scipy matplotlib
# Obtain mfoil.py from https://websites.umich.edu/~kfid/codes.html  (MIT licence)
# Place in ./vendor/mfoil.py ; keep the licence header intact.
```

Verify the baseline before touching anything:

```python
from vendor.mfoil import mfoil
m = mfoil(naca='2412', npanel=199)
m.setoper(alpha=2, Re=1e6)
m.solve()
```

Expect a converged viscous solution with cl, cd, cf and a Cp distribution. If this does not run, stop and fix it first.

### 7.2 T1 — Introspect mfoil's global system

**Do not assume attribute names from this document.** Introspect. What you must locate:

| Needed | What to look for |
|---|---|
| State vector **U** | The augmented global unknown vector (BL variables + panel/vorticity unknowns) |
| Residual **R(U)** | The assembled global residual |
| Jacobian **∂R/∂U** | Sparse matrix, assembled analytically |
| Node coordinates **x** | Panel node array driving geometry |
| Cp / edge-velocity extraction | Map from **U** to surface Cp at each node |
| Newton update / limiter | The under-relaxation ω logic (a single global value keeping θ and δ* from decreasing more than 50%, and enforcing Hk > Hk,min ≈ 1.00005 on the airfoil, 1.02 in the wake) |

Write a short note (`docs/mfoil_internals.md`) recording the actual names, shapes and call order. Everything downstream depends on it.

**Key question to answer here:** does mfoil expose **∂R/∂x** (residual sensitivity to node coordinates) analytically? If yes, the chain rule in §7.6 is exact and cheap. If not, see the fallback in §7.6.

### 7.3 T2 — CST module

`cst/basis.py`:

```python
def bernstein(n, i, psi):            # K_i psi^i (1-psi)^(n-i)
def class_fn(psi, N1=0.5, N2=1.0):   # psi^N1 (1-psi)^N2
def surface(psi, A, zeta_T, N1=0.5, N2=1.0):
    """zeta = C(psi) * sum_i A_i S_i(psi) + psi * zeta_T"""
def dsurface_dA(psi, n, N1=0.5, N2=1.0):
    """Returns the (len(psi), n+1) matrix  C(psi) * S_i(psi).
       DESIGN-INDEPENDENT — assemble once, cache it."""
def le_modification(psi, A_lem):     # Kulfan LEM term
```

Requirements:

- `dsurface_dA` must be **cached**. It does not depend on A. Recomputing it per Newton iteration is the single most common way to lose the performance argument.
- Support `n` per side independently, but default to equal.
- Sign convention: document explicitly whether lower-surface coefficients are stored negative. Every constraint in §7.6 depends on it.

`cst/geometry.py`:

```python
def coords_from_A(A_upper, A_lower, zeta_T_u, zeta_T_l, psi_dist):
    """Return (x, y) node arrays in the ordering mfoil expects
       (trailing edge -> upper -> LE -> lower -> trailing edge,
        or whatever T1 established)."""
def cosine_spacing(npanel):
    """Cosine clustering at LE and TE. Clustering matters for FM-3."""
```

`cst/fit.py`:

```python
def fit_cst(x, y, n, zeta_T=None):
    """Least-squares fit of CST coefficients to a given airfoil.
       Report residual RMS and the Gram-matrix condition number."""
```

**Validation gate for T2:** fit CST to NACA 2412 and to the PhD's sCO2 baseline blade section. Target RMS < 0.1% chord. Record `cond(GᵀG)` versus n — this is the empirical FM-2 curve and you will need it in the paper.

### 7.4 T3 — Constraint functionals (closed form)

`cst/constraints.py`. Each returns a **row vector** `g` and scalar `b` such that `g · A = b`.

```python
def le_radius_row(n, R_LE, chord=1.0):
    """A_0 = sqrt(2 R_LE / c). Single nonzero entry."""
def shared_le_radius_row(n):
    """A_u0 - |A_l0| = 0. Couples the two coefficient blocks.
       Equivalent to G2 curvature continuity at the nose (see 3.3)."""
def te_wedge_row(n, beta, dz_TE, chord=1.0):
    """A_n = tan(beta) + dz_TE/c."""
def area_row(n, N1=0.5, N2=1.0):
    """Closed form via the Beta function:
         int_0^1 C(psi) S_i(psi) dpsi = K_i * B(i + N1 + 1, n - i + N2 + 1)
       For N1=0.5, N2=1.0:  K_i * B(i + 1.5, n - i + 2).
       Use scipy.special.beta. Add zeta_T/2 for the TE term."""
def curvature_derivative_continuity_row(n):
    """Involves A_u1 and A_l1 (see 3.3). Optional; use if G3 is wanted."""
```

**Validation gate for T3:** verify `area_row` against numerical quadrature of the fitted NACA 2412 to 1e-10. This is a cheap, decisive check that the Beta-function algebra is right.

### 7.5 T4 — Analytic linear pre-solve (initialisation + realisability)

This is **not** the answer; it is the initialiser and the feasibility gate. Two jobs, both essential:

1. **Put Newton inside its basin of attraction** — critical because the LE region is exactly where Newton wanders, and mfoil's own documentation warns that the coupled solver fails from poor initial guesses.
2. **Realisability projection** — if the target cannot be represented in the CST-spanned subspace, you learn it *before* burning a Newton solve. This is the analytic counterpart of Lavagnoli's statistical predicted-RMS feasibility proxy.

**Method.** Thin-airfoil theory is linear in camber slope (vortex sheet) and thickness (source sheet). CST camber ζ_c = (ζ_u + ζ_l)/2 and thickness ζ_t = (ζ_u − ζ_l)/2 are linear in **A**. Therefore

```
Cp_target ≈ M · A
```

with **M** assembled either analytically (thin-airfoil kernels integrated against the Bernstein basis — Joseph & Mohan's Beta-function results, §5.4) or numerically from mfoil's own linear-vorticity panel influence coefficients at fixed geometry.

**Pragmatic recommendation: build M numerically from mfoil's inviscid panel operator first.** It is a few hours' work, exercises the same code path as the Newton coupling, and defers the Joseph & Mohan algebra until you know you need it.

Solve the constrained least-squares with the §7.4 rows as linear equality constraints — a KKT system, still closed-form:

```
[ MᵀM   Gᵀ ] [ A ]   [ Mᵀ Cp_target ]
[ G     0  ] [ λ ] = [ b            ]
```

**Realisability metric:** `||M·A* − Cp_target|| / ||Cp_target||`. Set a threshold (start at 5%); above it, warn that the target is likely outside the CST-representable manifold and Newton will stagnate rather than converge.

### 7.6 T5 — The extended Newton system (core deliverable)

**Unknowns:**

```
U   flow state             (N_tot)
A   CST coefficients       (n_A = 2(n+1), less any eliminated)
α   angle of attack        (1)   [or stagger in cascade]
```

**Equations:**

```
R(U; x(A)) = 0                     flow residual              (N_tot)
T(U) − Cp_target = 0               at M target stations       (M)
G·A − b = 0                        geometric equalities       (K)
```

**Jacobian:**

```
        ⎡ ∂R/∂U   ∂R/∂A   ∂R/∂α ⎤
   J =  ⎢ ∂T/∂U     0     ∂T/∂α ⎥
        ⎣   0     ∂G/∂A     0   ⎦
```

**Squareness condition (FM-1):**

```
N_tot + M + K  =  N_tot + n_A + 1     ⟹     M + K = n_A + 1
```

Assert this at construction time and raise on violation. Log the numbers every run.

**Block notes:**

- `∂R/∂U` — mfoil already assembles this analytically and sparsely. Reuse unchanged.
- `∂R/∂A = (∂R/∂x)(∂x/∂A)`, where `∂x/∂A = C(ψ)Sᵢ(ψ)` is the **cached, design-independent** matrix from T2. This is the whole point of the hypothesis and must be exact.
- `∂T/∂U` — Cp at a node is a direct function of the panel/edge-velocity unknowns, so this is close to a **selection matrix**. Cheap.
- `∂G/∂A = G` — constant. Free.

**If ∂R/∂x is not available analytically (likely):**

Do **not** finite-difference over node coordinates (N_panel columns). Finite-difference or complex-step **directly with respect to A** — only ~20 columns, i.e. 20 residual *evaluations* (not solves) per Newton step. That is negligible against one converged flow solve, and it preserves the architectural claim entirely.

Complex-step gives machine-precision derivatives but requires the residual path to be free of `abs`, `max`, `min` and comparison-based limiters. mfoil's update limiter contains such operations — but the *residual assembly* may not. **Check this; if the residual path is complex-safe, use complex-step and say so in the paper**, because it removes any FD-truncation objection to the conditioning results.

**Solve:** sparse LU (`scipy.sparse.linalg.splu`). Reuse mfoil's under-relaxation ω logic on the U block; apply a separate, more permissive trust region on the A block (geometry can move further than BL variables without becoming unphysical).

### 7.7 T6 — Diagnostics (build these before you need them)

Every one of these exists to discriminate between the four failure modes. Without them, all four look like "it diverged."

| ID | Diagnostic | Discriminates |
|---|---|---|
| D-1 | Per-block residual norms: ‖R‖, ‖T‖, ‖G‖ per iteration | Which block stalls |
| D-2 | `rank(J)` and `cond(J)`; rank of the `[∂R/∂A; ∂G/∂A]` sub-block | **FM-1** (rank deficiency masquerading as LE divergence) |
| D-3 | `cond(GᵀG)` of the CST Gram matrix vs n | **FM-2** |
| D-4 | Row-norm profile of `∂R/∂A` vs chordwise station | **FM-3** — expect a spike at the nose |
| D-5 | Transition-location history per iteration | **FM-4** — oscillating transition = chatter |
| D-6 | Newton convergence history (log ‖R‖ vs iteration) | Quadratic tail confirms the architectural claim |

D-6 is the headline figure of the paper. D-2 is the one that will save the most time.

### 7.8 T7 — The falsifiable test

**The single experiment that settles the hypothesis:**

1. Take a known airfoil — start with NACA 2412, then the PhD's sCO2 baseline section.
2. Fit CST to it (T2). Record the exact coefficient vector **A\***.
3. Run mfoil in **direct** mode. Extract the surface Cp distribution. This is `Cp_target`.
4. Perturb **A\*** to get a starting guess (or use the T4 pre-solve, which should land near **A\***).
5. Run the monolithic CST-Newton inverse against `Cp_target`.
6. **Does it recover A\*?**

Why this test and not another: it is a self-consistency check with a **known answer**, **guaranteed realisable** by construction. Any failure therefore isolates cleanly to one of the four failure modes rather than to target infeasibility.

**Success criterion:** ‖A − A\*‖∞ < 1e-4 in single-digit Newton iterations, with a visible quadratic tail in D-6.

**If it converges: the hypothesis is demonstrated.** If it does not, the D-1…D-6 residual pattern tells you which failure mode you are in.

### 7.9 T8 — Ablations (the paper's evidence base)

Run each with the T7 harness:

| Ablation | Tests |
|---|---|
| n = 4, 6, 8, 10, 12, 16 per side | FM-2; find the conditioning cliff |
| LE treatment: none / Kulfan LEM / Masters unwrapped / prescribed first 5% chord | FM-3; **expect prescribed-LE to be the most robust** |
| Transition: forced trip vs free | FM-4 |
| M + K = n_A + 1 vs deliberately over/under-determined | FM-1; confirm D-2 catches it |
| Initialisation: T4 pre-solve vs baseline airfoil vs random | Validates the pre-solve's necessity |
| Control: same problem via scipy least-squares over mfoil calls | The nested-optimization baseline for the flow-solve-count comparison |

The last row is essential. The headline claim is a **count of flow solves**, and it needs a fair, tuned baseline to be credible.

### 7.10 Target-realisability caveat (carry into the write-up)

Inverse problems are ill-posed and non-unique — multiple shapes can produce nearly the same Cp, and the closure and free-stream constraints (Lighthill, Volpe & Melnik) are what restore well-posedness. A prescribed target may simply be physically unrealisable. The T4 realisability metric is the guard; state it explicitly rather than letting a stagnating Newton be read as a failure of the method.

---

## 8. STAGE 2 — Cascade extension (design, not yet built)

Once Stage 1 converges, the physics gap must close: turbine cascades with high turning (the sCO2 baseline turns well beyond 100°) are nothing like an isolated airfoil.

### 8.1 What must be added to mfoil

| Feature | Why | Difficulty |
|---|---|---|
| **Cascade periodicity** | Blade row, not isolated airfoil | Moderate — closed form, see §8.2 |
| **Pitch / solidity / stagger** | Geometry definition | Easy |
| **Inlet/outlet angle boundary conditions** | Cascade Kutta and periodicity closure | Moderate |
| **AVDR / streamtube contraction** | Q3D effect; MISES's m′–θ formulation | Moderate |
| **Higher compressibility** | Kármán–Tsien is subcritical only | Hard — see §8.5 |

### 8.2 Cascade periodicity — the key substitution

For an infinite linear cascade of pitch `s`, the complex potential of an infinite row of point vortices spaced `s` apart is

```
w(z) = (iΓ / 2π) · ln[ sin( π (z − z₀) / s ) ]
```

and for an infinite row of sources,

```
w(z) = (m / 2π) · ln[ sin( π (z − z₀) / s ) ]
```

**The entire modification to the panel influence kernel is:**

```
ln(z − z₀)   →   ln[ sin( π (z − z₀) / s ) ]
```

Differentiate for induced velocity. As `s → ∞` this reduces to the isolated-airfoil kernel, giving a free regression test: **set s = 10⁶ and reproduce Stage 1 results exactly.**

Note that for a linear-vorticity (rather than point-vortex) panel method, the panel-integrated influence coefficients must be re-derived with the new kernel — either analytically or by adaptive quadrature. Quadrature is the safer first implementation; optimise later if it dominates runtime.

### 8.3 Cascade Kutta and closure

The isolated-airfoil Kutta condition generalises, but the cascade adds a relation between inlet angle, outlet angle and circulation:

```
Γ = s · (V_inlet,tangential − V_outlet,tangential)
```

This is an extra Newton row. Decide explicitly whether inlet angle is prescribed and outlet angle is an unknown (usual for turbine analysis) or vice versa; the choice changes the DOF accounting of §7.6 and must be re-asserted.

### 8.4 Validation ladder

1. **s → ∞** reproduces Stage 1 exactly (regression test).
2. **Gostelow's exact cascade solutions** (Gostelow, *Cascade Aerodynamics*, Pergamon, 1984) — analytic incompressible cascade profiles with known surface velocity distributions. This is the decisive inviscid validation.
3. **Hobson** cascade solutions as a second analytic reference.
4. **MULTALL Q3D blade-to-blade** as an independent numerical check on the same geometry (§6.3). Note MULTALL is time-marching, so it validates the *answer*, not the method.
5. **The PhD's own MISES-validated sCO2 blade** — the surface Mach distributions were validated against wind-tunnel cascade tests (UTRC, DFVLR, ARL comparisons in the thesis appendix), giving a physically anchored end-to-end case.

### 8.5 Compressibility — the honest limit

Kármán–Tsien is subcritical only. For transonic turbine cascades this is inadequate, and there is no cheap fix within a panel method. Options:

- **Accept subcritical scope for Stage 2** and defer transonic to Stage 3 (MISES). Recommended.
- Replace the inviscid core with a streamline-grid Euler solver (i.e. rebuild ISES) — a large project, but it is precisely the "open-source Newton-coupled cascade solver" gap identified in §6.4, and would be a standalone contribution.

### 8.6 Targets for Stage 2

- Target-vs-achieved surface Mach RMS < 0.005
- Outlet flow angle error < 0.1°

These are calibrated against Lavagnoli's KAN results (mean outlet-angle error 0.086°, Mach RMS 0.004) so the comparison is like-for-like.

---

## 9. STAGE 3 — MISES (transonic, viscous, real cascade)

Prerequisites: Stage 1 converged; Stage 2 validated against Gostelow; MISES licence resolved (§6.1).

### 9.1 Two implementation routes

**Route A — Modal-Inverse via `modes.xxx` (recommended first).** Because CST is linear in **A**, its basis functions *are* valid perturbation modes (§1.6). Write `C(ψ)Sᵢ(ψ)` sampled on the blade surface into MISES's mode file format. **No Fortran modification required.** MISES then adds the mode amplitudes to its own Newton system and drives them to match the target — exactly the monolithic architecture, obtained for the cost of a file writer.

This should be attempted before anything else. If it works, the hypothesis is demonstrated in the real solver with near-zero code.

**Route B — Parametric-Inverse via `BPREAD`/`BLDGEN`/`BPWRIT`.** Implement CST as MISES's black-box geometry generator; use `SUBROUTINE BPCON` to impose the area, thickness and LE-radius constraints of §7.4 natively. More work, but gives constraint handling inside MISES rather than bolted on.

Note that Parametric-Inverse is documented as a *best fit* to the target — a Gauss–Newton least-squares — whereas Modal-Inverse is a determined root-find. **For the purposes of this hypothesis, Modal-Inverse is the architecturally correct target.** Route B is the fallback if mode-file coupling proves inadequate.

### 9.2 Practical notes

- Seed the Newton iteration with the Stage 1 analytic pre-solve (§7.5). This is the decisive move: analytic initialisation inside the singular LE region is what prevents the divergence documented in the thesis.
- Use the MISES 2.63 sensitivity dump (∂Cp/∂parameter, ∂Hk/∂parameter) to monitor conditioning — it is the D-2/D-4 diagnostic, already built in.
- Enable the Pcorr streamline-tension term. Per the MISES documentation it is "really only required in inverse cases and in viscous cases with boundary layer separation" — both apply here.
- Beware small leading-edge radii: the MISES guide notes that with small LE radii the range of tolerable inlet slopes is quite small, and that a poor inlet slope produces Cp spikes and start-up trauma for the subsequent viscous solution. Directly relevant to FM-3.

---

## 10. Publication plan

| Paper | Content | Venue |
|---|---|---|
| **P1** | Monolithic CST-Newton inverse design: formulation, DOF accounting, conditioning analysis, isolated-airfoil demonstration on mfoil, flow-solve-count comparison against nested optimization | *AIAA Journal* or AIAA SciTech |
| **P2** | Cascade extension: periodic panel kernel, Gostelow validation, turbine cascade inverse design | ASME *J. Turbomachinery* or ASME Turbo Expo |
| **P3** (optional) | Open-source Newton-coupled cascade solver with CST-native inverse mode — filling the §6.4 gap | *J. Turbomachinery* / software paper |

**Novelty positioning for P1:** the contribution is *not* "geometry unknowns in the Newton system" (Drela, 1986/1990) and *not* "CST used in inverse design" (Lane & Marshall, 2010, where CST is a smoother). It is the combination — **a complete analytic basis whose linearity makes the geometric Jacobian exact and constant, and whose geometric functionals make design constraints linear rows, together converting constrained shape optimization into constrained root-finding.**

**Before submitting:** confirm the §5.6 negative result with a targeted search of the AIAA and ASME Digital Collections. The absence of prior CST–MISES-inverse coupling is currently based on web search, not an exhaustive library check.

---

## 11. Verification notes and caveats

- **Reference metadata.** DOIs and page numbers in §5 were gathered from search results and a literature-survey pass; the MISES, mfoil and MULTALL links in §6 were directly retrieved. Verify §5 citations against the publisher record before they appear in a manuscript. The Lavagnoli *Energies* paper carries a 2026 publication date (10 June 2026) — treat as very recent and check final pagination.
- **Some cited items are conference papers or preprints** (arXiv, MDPI, Chinese-language journals). The generative/diffusion results in particular are fast-moving and not all peer-reviewed to journal standard; treat quantitative claims such as the 34.4% CDDPM improvement as provisional.
- **mfoil internals.** Attribute names are deliberately not asserted in §7. Introspect and record them (T1) before writing coupling code.
- **Licensing.** Resolve the MISES commercial-versus-academic question (§6.1) before Stage 3 work begins. mfoil (MIT), MULTALL (free), XFOIL (GPL) carry no such constraint; note that GPL linkage would affect distribution of any XFOIL-derived work.
- **Do not overclaim "closed form."** The closed-form component is strictly the linearised thin-airfoil kernel and the constraint functionals. Everything viscous, transonic and finite-thickness requires Newton iteration. The claim is *semi-analytical architecture with no outer optimization loop* — which is strong enough on its own.

---

## Appendix A — Quick-reference links

**Solvers**
- MISES project page — https://web.mit.edu/drela/Public/web/mises/
- MISES user guide (public PDF) — https://web.mit.edu/drela/Public/web/mises/mises.pdf
- MIT TLO MISES licensing — https://tlo.mit.edu/industry-entrepreneurs/available-technologies/mises-software-design-and-analysis-turbomachinery
- MISES non-commercial EULA — https://web.mit.edu/tlo/documents/MISES_EULA_noncommercial_2021_05.pdf
- mfoil (code + docs) — http://www-personal.umich.edu/~kfid/codes.html
- mfoil documentation PDF — https://websites.umich.edu/~kfid/codes/mfoil/mfoil.pdf
- mfoil paper PDF — https://public.websites.umich.edu/~kfid/MYPUBS/Fidkowski_2023_mfoil.pdf
- XFOIL — https://web.mit.edu/drela/Public/web/xfoil/
- MULTALL-open — https://sites.google.com/site/multallopen/home
- MULTALL GitHub mirror — https://github.com/paopaoai11/Multall-open-18.3

**Key DOIs**
- Fidkowski mfoil, *AIAA J* 60(5), 2022 — https://doi.org/10.2514/1.J061341
- Kulfan, *J. Aircraft* 45(1), 2008 — https://doi.org/10.2514/1.29958
- Masters et al., *AIAA J* 55(5), 2017 — https://doi.org/10.2514/1.J054943
- Joseph & Mohan, *AIAA J* 59(10), 2021 — https://doi.org/10.2514/1.J060859
- Souto Torres & Marques, *Meccanica*, 2024 — https://doi.org/10.1007/s11012-024-01801-6
- Wang, Wang & Sun, *Proc. IMechE G*, 2021 — https://doi.org/10.1177/0954410020984570
- Denton MULTALL, *J. Turbomach.* 139(12), 2017 — https://doi.org/10.1115/1.4037819
- Lavagnoli, *Energies* 19(12), 2026 — https://doi.org/10.3390/en19122796
- LF-PINN inverse design (uses mfoil), *AIAA J* — https://doi.org/10.2514/1.J063570
- Yilmaz & German cGAN, AIAA 2020-3185 — https://doi.org/10.2514/6.2020-3185
- CDDPM, *SMO*, 2025 — https://doi.org/10.1007/s00158-025-04111-x

---

## Appendix B — Stage 1 task checklist

```
[ ] T0  Environment; mfoil baseline NACA 2412 viscous solve reproduces
[ ] T1  Introspect mfoil globals; write docs/mfoil_internals.md
        [ ] Determine whether dR/dx is available analytically
        [ ] Determine whether the residual path is complex-step safe
[ ] T2  CST module: basis, surface, cached dsurface_dA, LEM, fit
        [ ] GATE: fit NACA 2412 and sCO2 baseline, RMS < 0.1% chord
        [ ] Record cond(G^T G) vs n
[ ] T3  Constraint rows: LE radius, shared LE radius (G2), TE wedge, area
        [ ] GATE: area_row matches quadrature to 1e-10
[ ] T4  Linear pre-solve: build M from mfoil panel operator; KKT solve
        [ ] Realisability metric implemented and thresholded
[ ] T5  Extended Newton system; assert M + K = n_A + 1
        [ ] dR/dA via cached chain rule, or complex-step over A
        [ ] Sparse LU; separate trust region on the A block
[ ] T6  Diagnostics D-1 .. D-6
[ ] T7  FALSIFIABLE TEST: recover A* from self-generated Cp target
        [ ] NACA 2412
        [ ] sCO2 baseline section
        [ ] SUCCESS: ||A - A*||_inf < 1e-4, single-digit iterations,
            quadratic tail in D-6
[ ] T8  Ablations incl. nested-optimization control baseline
[ ] T9  Stage 2 design review; decide on cascade kernel implementation
```
