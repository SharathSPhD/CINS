# ADR-0004: realisability metric semantics (inviscid representability vs viscous model gap)

**Status:** accepted, 2026-08-04 · **Trigger:** T4/T5/T7 adversarial review, CONFIRMED
finding — the logged realisability (0.0004–0.0008) was computed against an inviscid
proxy target, while the actual viscous forced-transition target gives 0.066, above
the 0.05 gate threshold.

## Analysis
The single number conflated two different questions:
1. **CST-representability** — can any coefficient step reproduce the target under the
   linearized model? This is what the dossier's realisability guard (§7.5) is for,
   and it is correctly answered with model-consistent quantities (inviscid target vs
   inviscid linearization → 0.0004: the target IS representable).
2. **Model gap** — how far is the inviscid linearization from the viscous physics the
   Newton solve will actually face? (0.066 here: the boundary layer's displacement
   effect, which no inviscid model captures, NOT target unrealisability. The
   subsequent monolithic solve converged to 1e-11 — proof the target was realisable.)

Gating question 1 with a number that mixes in question 2 would produce false
infeasibility warnings on every viscous problem; logging only question 1 while
implying it validated the viscous problem was the review's (correct) objection.

## Decision
- `presolve` reports **realisability** strictly as metric 1 (model-consistent), with
  the docstring stating its scope explicitly.
- The driver additionally logs **model_gap** (metric 2) whenever a viscous target is
  in play; it is diagnostic, not gating. Its empirical range (0.06–0.07 on the T7
  case) becomes a baseline; T8 records it per ablation cell. If model_gap correlates
  with Newton failures in T8, promote it to a gated warning with its own threshold.
- Paper/reporting rule: realisability numbers are always labeled with their model
  ("inviscid-consistent"); the conditioning of the QR-selected station submap
  (cond≈90) must never be quoted as the conditioning of the full extended Newton
  system (cond≈1.6e8 at Nsys=230 — recorded by D-2); they are different matrices
  answering different questions.
