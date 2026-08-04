# tests — TDD contract (BINDING)

- Red → green → refactor. A feature PR without a preceding failing test is rejected in review.
- Layout: `unit/` (fast, pure-math), `gates/` (dossier numeric criteria — the gate-closure
  evidence), `regression/` (pinned numbers from closed gates).
- **Gate tests may never be weakened** (tolerance loosened, case removed, skip added)
  without an ADR in `docs/adr/` linked in the commit message.
- Gate thresholds are read from `configs/default.yaml` (`gates:` section) so tests and
  runtime share one source of truth — tests assert against the config value, and the
  config value change itself requires an ADR.
- Every closed gate adds a regression test pinning its measured numbers (tolerance from
  GATES.md) so later work cannot silently degrade earlier results.
- Property-based tests (hypothesis) encouraged for CST math (linearity in A, endpoint
  identities S(0)=A₀, S(1)=Aₙ).
- No test may depend on matplotlib rendering; mfoil is always constructed with plotting off.
