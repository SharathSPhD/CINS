# Pre-submission novelty search

Date: 2026-08-05. Closes the search obligation recorded in the research dossier
sections 5.6 and 11, and the corresponding item in the Stage 1 closure report.

## Claim under test

The contribution asserted for P1 is the combination of three properties, not any
one of them alone:

1. geometry coefficients of a complete analytic basis entering a Newton-coupled
   viscous and inviscid flow solver's own global system as unknowns;
2. geometric design constraints entering the same system as exact linear rows;
3. the resulting problem being square and determined, so it is solved by
   root-finding rather than by an outer optimization loop.

Individually, item 1 is established prior art. Drela's Modal-Inverse formulation
adds geometry mode amplitudes to the MISES global Newton system and drives them
to match a target surface speed. Any novelty claim that rests on item 1 alone is
invalid and the manuscript does not make one.

## Searches performed

| Query focus | Result |
|---|---|
| CST coefficients as unknowns in a Newton system coupled to MISES | No matching work. Results cover CST in gradient-based and surrogate optimization, quasi-Newton optimizers acting on CST variables, and neural-network inverse mappings. |
| Modal-Inverse, mode amplitudes as Newton unknowns, 2020 to 2026 | Confirms the Drela lineage: a full Newton solution gives flowfield sensitivities to predefined shape deformation modes and to rigid-body translation and rotation modes. Modes are heuristic or user-supplied, not a complete analytic geometry basis, and constraints are not linear rows of the same system. |
| Prior art on CST used within inverse design | AIAA 2010-1228 remains the nearest work. See the attribution correction below. |

## Attribution correction

AIAA 2010-1228, "Inverse Airfoil Design Utilizing CST Parameterization", is by
Kevin A. Lane and David D. Marshall of California Polytechnic State University,
San Luis Obispo, presented on 4 January 2010 at the 48th AIAA Aerospace Sciences
Meeting in Orlando. The research dossier attributed it to Morris, Allen and
Rendall, and that error propagated into the manuscript bibliography and body
text. Verified against the Cal Poly Digital Commons record and the AIAA ARC
listing. The bibliography, the in-text citations and the comparison table have
been corrected.

The characterisation of that work is unchanged and remains accurate. Lane and
Marshall drive shape changes from pressure residuals, using the sign of the
surface normal to decide the direction of the correction, and use CST as a
smoothing algorithm applied to that correction. The flow solver is deliberately
kept separate from the design process so that any solver may be used. The
coefficients are therefore not unknowns of a flow solver's Newton system, and no
constraint rows exist. The construction is structurally different from the one
presented here.

## Related work that does not overlap

- Modal-Inverse and Mixed-Inverse in MISES: geometry unknowns in a Newton system,
  but with heuristic modes and without linear constraint rows.
- CST with adjoint methods, for example in SU2: gradients with respect to CST
  coefficients, used to drive an optimizer. The formulation remains an
  optimization, which is the class of method this work avoids.
- Learned inverse mappings, including conditional GANs, diffusion models and
  physics-informed networks: fast inference after training, with no convergence
  guarantee for an individual target and no mechanism for exact geometric
  constraints.
- Parameterization comparison studies, for example Masters and co-authors:
  establish CST as an efficient analytic basis, but do not couple it to a solver's
  Newton system.

## Conclusion

No published work was found that places the coefficients of a complete analytic
geometry basis into a Newton-coupled viscous and inviscid solver's global system
while expressing geometric constraints as exact linear rows of that same system.
The negative result from the dossier stands after this targeted search, with the
attribution of the nearest prior art corrected.

## Limitation of this search

The search used public web indexes and publisher listings. It is not a
substitute for a full text search of the AIAA and ASME digital collections behind
their subscription interfaces. A subscription-side search should be run before
submission, and this document should be updated with its date and outcome.
