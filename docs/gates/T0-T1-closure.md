# Gate closure records — T0, T1 (retroactive, stock-take remediation)

Written 2026-08-04 after the Stage 1 stock-take flagged that T0/T1 lacked the
formal closure documents T2–T8 have. Both gates were factually closed on
2026-08-04 with the evidence below; this document formalizes the record.

## T0 — environment + baseline
- Evidence: vendored mfoil v2023-06-28 (provenance + dual hashes in
  vendor/mfoil/PROVENANCE.md); NACA 2412 α=2° Re=1e6 viscous solve converged
  (cl=0.4494, cd=0.00578, quadratic tail to 1e-11), pinned in
  tests/gates/test_t0_baseline.py and site/gates.json (commit 514579f).
- Review: no adversarial review was run for this smoke gate (deviation noted);
  the baseline numbers have since been re-verified by every downstream gate,
  the app's live API, and the stock-take's independent suite run.

## T1 — mfoil internals introspection
- Evidence: docs/mfoil_internals.md (742 lines, line-cited), answering the two
  architecture questions (R_x partial → FD-over-A; complex-step blocked) that
  T5 then implemented successfully — empirical downstream validation.
- Review: findings were verified against running code by the introspection
  agent itself (empirical tests, not just reading); the two vendor bugs it
  found were later independently confirmed by the T2 agent and fixed via
  ADR-0002. No separate adversarial pass was run (deviation noted); the
  document's load-bearing claims (derivative strategy, rebuild sequence,
  traps 1–7) were all exercised by T5–T8 without contradiction.

## Stock-take remediation notes
- experiments/results/t2_gram_conditioning.json: restored to its closure-time
  manifest (a gate-test rerun had refreshed the stamp; data unchanged).
  Pending small fix: the T2 gate test should verify-not-overwrite the archive.
