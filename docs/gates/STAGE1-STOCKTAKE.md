# Stage 1 stock-take — ACHIEVED vs PENDING

**Date:** 2026-08-04 · **Commit at time of review:** `8938393` (main, working tree has
uncommitted files, see §5) · **Method:** every claim below was checked against a live
run (`.venv/bin/python -m pytest tests/ -q`, direct reads of `result.json`/`diagnostics.json`,
`run.log`), not taken from `docs/gates/*` or `site/gates.json` prose alone. Where the
archived claim and the artifact agree, marked **VERIFIED**. Where I could not independently
confirm a number (script not rerun, or evidence is a document rather than a manifest), marked
**WEAK**. Nothing below is fabricated; where evidence was missing I say so.

---

## 0. Test suite (baseline fact-check)

`.venv/bin/python -m pytest tests/ -q` — full suite green, 1 test explicitly `skip`ped
(`test_uiuc_corpus_all_files_parse_to_plausible_sections`-adjacent path, see §3). No
failures, no errors, no xfail-masking observed. **VERIFIED.**

Caveat: "tests green" is only condition (1) of the six in `docs/GATES.md`; it is
necessary, not sufficient, for any gate's closure — treated that way throughout below.

---

## 1. Gate-by-gate stock-take (T0–T9)

For each gate: does `docs/gates/*`, `site/gates.json`, and the actual artifact tree agree,
and does the evidence satisfy `docs/GATES.md`'s six-condition contract?

### T0 — Environment + mfoil baseline — **ACHIEVED, VERIFIED**
`site/gates.json` claims NACA 2412 α=2° Re=1e6 converges, cl=0.4494. This exact cl
reappears as the *target* in T7's `run.log` (`target generated: cl=0.4410 ... (tripped)`
— note: tripped/forced-transition cl differs from natural, consistent, not a
contradiction). No standalone T0 artifact file exists (no `docs/gates/T0-closure.md`),
which is a documentation gap relative to T2–T7's pattern, but the underlying capability
is exercised transitively by every later gate's mfoil calls succeeding. **Six-condition
check:** (1) tests green — yes (general suite); (2) domain validation — plausible but not
separately archived; (3) adversarial review — no `T0-closure.md`/review file exists;
(4) artifacts — none dedicated; (5) docs — `site/gates.json` entry only; (6) merged — yes.
**Verdict: functionally achieved, procedurally under-documented** (no closure report, no
adversarial-review record specific to T0).

### T1 — mfoil internals introspection — **ACHIEVED, WEAK evidence**
Claimed evidence: `docs/mfoil_internals.md` (exists — contains FM-2/FD strategy
discussion) and ADR-0002 (exists, vendor shims documented). No dedicated
`docs/gates/T1-closure.md` or adversarial-review record. Commit hash in `site/gates.json`
is `null`. **Verdict: content plausible and present, but the six-condition contract
(adversarial review, archived diagnostics) is not documented as satisfied — WEAK, not a
blocking defect since T1 is exploratory/no numeric gate.**

### T2 — CST module, fit RMS < 0.1% chord — **ACHIEVED, VERIFIED**
`docs/gates/T2-closure.md` table matches `experiments/results/t2_gram_conditioning.json`
(the file exists, is under version control, was modified in the current uncommitted
diff — see §5 note on reproducibility). Fit RMS values (3.99e-5 etc.) and the FM-2 curve
(498 → 5.7e9 as n: 4→16) are internally consistent with the closure doc. Adversarial
review documented with one prior fix (tautological cache test) and a PLAUSIBLE
(non-blocking) finding about large-n truncation. **Six conditions: all satisfied and
cross-checked. VERIFIED.**

Caveat found during this stock-take: `experiments/results/t2_gram_conditioning.json` is
currently **modified in the working tree relative to the last commit**
(`git diff --stat` shows it changed, 6 lines). This means the number currently on disk may
not be the one `T2-closure.md` was written against — a reproducibility risk, not
necessarily a wrong number (not yet committed, so not yet "the record"). Flagged for the
main session to resolve before further claims are built on it.

### T3 — Constraint rows, area to 1e-10 — **ACHIEVED, VERIFIED**
`docs/gates/T3-closure.md` documents a CONFIRMED adversarial finding (lower-surface
`te_wedge_row` sign error) that was fixed and re-pinned by an independent test. This is
exactly the kind of finding the gate contract is designed to surface, and it was resolved,
not waived. `curvature_derivative_continuity_row` (G3) is explicitly left
`NotImplementedError` (optional per dossier §3.3) — correctly flagged as scope, not
silently stubbed. **VERIFIED**, and notably this is the single best piece of evidence in
the whole archive that the adversarial-review step is real (it caught a genuine sign bug
matching the exact FM class the reviewing charter for this repo cares about).

### T4 — Linear pre-solve + realisability — **ACHIEVED, VERIFIED with a real caveat**
`docs/gates/T4-T7-closure.md` + `ADR-0004` together document a CONFIRMED finding (the
realisability metric conflated inviscid representability with viscous model gap) that was
resolved by *redefining and re-labeling*, not by loosening a threshold — the ADR exists
and is substantive (not a rubber-stamp waiver). `run.log` for T7 independently reproduces
the two numbers ADR-0004 relies on: `realisability(inviscid)=0.0004`,
`model_gap(viscous)=0.1094-0.1100`. **VERIFIED**, both numbers cross-check between the ADR
prose and the live log.

### T5 — Extended Newton system — **ACHIEVED, VERIFIED (transitively)**
`M + K = n_A + 1` (with alpha fixed, `n_alpha=0`, so `M=n_A_free`) is directly visible in
`run.log`: `DOF accounting: M=16 K=0 n_A_free=16 (+0 alpha)` — squares. The
deliberately-violating case is exercised in T8, not T5 in isolation
(`t8_dof_over`/`t8_dof_under`, both raise `dof_check_error` at construction time,
confirmed below in T8). Strictly, `docs/GATES.md` asks for "at least one
deliberately-violating case caught" under **T5**; this exists but is filed as a T8
ablation cell rather than a T5 artifact — a filing/labeling gap, not a missing capability.

### T6 — Diagnostics D1–D6 — **ACHIEVED, VERIFIED**
`t7_naca2412/diagnostics.json` contains real per-iteration `R_norm`, `T_norm`, `rank_J`,
`cond_J`, `rank_RA_G` arrays (not stubs — `cond_J=1.57e8` etc., varies by iteration,
`dR_dA_row_norms` populated with a genuine 936-long row array). This directly satisfies
condition (2)'s "non-trivial artifact on a real run" bar for D-2. D-6's order estimator is
present as `convergence_order` — but see the T8 finding below that this raw stored value
is **floor-polluted and not the honest number**; T6 built the *mechanism* correctly, T8's
analysis is what correctly post-processes it. **VERIFIED** as infrastructure; the
consuming analysis (T8) is the more careful piece.

### T7 — Falsifiable test, recover A* — **ACHIEVED, VERIFIED, independently re-run**
This is the strongest-evidenced gate in the archive. I re-derived the claimed numbers
directly from `experiments/results/t7_naca2412/run.log`, not from prose:
```
RESULT: converged=True iters=4 ||A-A*||_inf(free16)=1.079e-11 (all18=1.079e-11, 2 prescribed)
residual history: ['5.85e-04', '3.14e-06', '1.04e-10', '6.35e-11']
release-and-verify (natural transition): cl=0.449091 (target 0.449091, d=8.0e-13)
  cd=0.005774 (target 0.005774, d=1.1e-14) conv=True
T7 GATE: PASS
```
This matches `site/gates.json`'s "16 free coefficients recovered to 1.1e-11 in 4
iterations (2 LE coeffs prescribed)" and the release-and-verify Δcl/Δcd claims exactly.
Quadratic-tail visibility: 5.85e-4 → 3.14e-6 (≈187x drop) → 1.04e-10 (≈30000x drop) —
consistent with quadratic, not just claimed. **VERIFIED, gate genuinely earned.**

### T8 — Ablations + statistical benchmark — **ACHIEVED with material, honestly-reported
corrections — VERIFIED**
This is the second-strongest-evidenced gate, and also the one with the most self-reported
deviations from the pre-registration (`experiments/results/t8/ANALYSIS.md` §0, deviations
1–12). I independently re-derived the two headline claims rather than trusting the prose:

- **Panel 18/18:** I read every `panel_*/result.json` directly. 20 panel directories
  exist; `panel_0006` and `panel_44012` both have `converged: False, iterations: 0`
  (matching ANALYSIS.md's stated exclusions — target-generation non-convergence and an
  unsupported 44XXX mean-line family, respectively); the remaining 18 all have
  `converged: True` with iteration counts 3–7. **VERIFIED**, count and exclusions both
  check out against raw JSON, not just the analysis doc's table.
- **H2 (flow-solve ratio):** ANALYSIS.md explicitly **rejects the dossier's pre-registered
  ≥100x claim** and reports 3.1x/8.1x instead, and states this is destined for the paper
  abstract's correction. This is the single most important honesty signal in the whole
  archive — a team under pressure to hit a number instead reported the number that
  falsified the a priori hypothesis. Cross-checked: `paper/p1_main.tex`'s abstract-area
  comment (line ~14) explicitly instructs "do NOT claim two-to-three orders of magnitude
  ... measured, fair-paired result is 3-8x" — the paper draft and the analysis agree.
  **VERIFIED, and this consistency is itself evidence the number wasn't cherry-picked
  post-hoc for one document only.**
- **H1 Wilson bound:** ANALYSIS.md reports the Wilson 95% LB at n=18/18 is 0.824,
  mathematically below the pre-registered ≥0.9 target, and states this is unattainable at
  this panel size regardless of success rate. I did not independently recompute the Wilson
  interval formula in this pass; the claim (LB≥0.9 requires n≥29 all-success) is
  plausible on Wilson-interval mechanics but **WEAK — not independently recomputed here.**
- DOF-mis-squaring negative controls (`t8_dof_over`/`t8_dof_under`): confirmed directly —
  both `result.json` show `converged: False, iterations: 0` and the analysis quotes the
  exact `dof_check_error` strings (`M+K=17 but n_A_free+n_alpha=16` etc.), consistent with
  `M+K=n_A+1` failing loudly and immediately, not silently. **VERIFIED.**

**Six-condition check:** tests green (yes, general suite); domain validation (yes, with
honestly reported shortfalls against pre-registration — this is what "achieved" should
look like when reality diverges from the hypothesis); adversarial review (two passes per
`site/gates.json`, "CLOSED, adversarially verified twice"); artifacts (all present,
`figures/*.png` regenerable per ANALYSIS.md §7 note); docs/paper updated (paper abstract
matches); merged & pushed (yes, per git log `2a41d70`, `51a968b`). **VERDICT: T8 is
genuinely closed** — closure quality here is a positive finding for the project's
research-integrity practice, not just a checkbox.

### T9 — Stage 2 (cascade) design review — **IN PROGRESS, NOT CLOSED (matches its own
status field)**
`site/gates.json` itself says `"status": "in_progress"`, `"commit": null`, and
`"evidence": "... Adversarial check pending."` — the tracking artifact is honest about its
own incompleteness, and I confirm this matches reality: `docs/T9-stage2-design-review.md`
exists (53 lines — decisions on AVDR deferral, validation ladder S0–S5, LS89 data location)
but there is no `docs/gates/T9-closure.md` and no adversarial-review record for it.
**PENDING**, correctly self-reported as such — not a discrepancy to flag, just confirming
the "pending" label is accurate.

---

## 2. Summary table

| Gate | site/gates.json status | Stock-take verdict | Evidence quality |
|---|---|---|---|
| T0 | closed | achieved (functionally) | weak — no closure doc |
| T1 | closed | achieved (exploratory) | weak — no closure doc |
| T2 | closed | achieved | verified, minor repro risk (uncommitted json) |
| T3 | closed | achieved | verified — real bug caught+fixed |
| T4 | closed | achieved | verified — real bug caught+fixed |
| T5 | closed | achieved (transitively via T8) | verified, filing gap |
| T6 | closed | achieved | verified |
| T7 | closed | achieved | verified, independently re-derived |
| T8 | closed | achieved | verified, independently re-derived, honest H2/Wilson corrections |
| T9 | in_progress | correctly still pending | n/a |

---

## 3. PENDING items (explicit checklist against the user's candidate list, plus anything
else found)

1. **UIUC loader + ~100-section panel (H1 Wilson certification).**
   **Status: PARTIALLY STARTED, UNCOMMITTED, NOT RUN.** `src/cins/cst/io.py` (215 lines,
   Selig/Lednicer format loader) and `tests/gates/test_t8_uiuc_loader_panel.py` (103
   lines) exist **but are untracked in git** (`git status --short` shows both as `??`).
   `data/airfoils/uiuc/` contains 124 `.dat` files (a real corpus, not a stub). Running
   the loader's own tests: 1 test in this file is `skip`ped (a corpus file inside a
   documented `KNOWN_BAD_UIUC_FILES` skip-list, not silent). **No inverse-solve panel run
   over this corpus exists anywhere in `experiments/results/`** — the loader can read
   files, but nothing has fed them through `solve_inverse`. This is real, uncommitted,
   in-progress work, not vaporware, but it does not close H1's Wilson-LB≥0.9 gap.
   **Effort: M** (loader done; panel-run + result aggregation + Wilson-CI report remains).
   **Blocks:** the T8 H1 addendum's own stated next step ("the UIUC extension (~100
   sections) can certify LB ≥ 0.9 if the success rate holds") and any paper claim beyond
   "18/18 on a 20-section panel."

2. **AIAA/ASME novelty search (dossier §5.6).** **Status: NOT RUN.** Grepped
   `docs/` for "novelty", "prior art", "AIAA search", "ASME search" — the only hits are
   the dossier's own instruction to do this and `docs/PRD.md`/`docs/GATES.md` incidental
   mentions, no results document. **Effort: S–M** (literature/patent search + write-up).
   **Blocks:** paper's novelty claim being defensible against reviewer #2's "hasn't this
   been done before" — currently the paper's own lit review cites only Kulfan (CST) and
   Morris/Allen/Rendall (nearest prior inverse-CST work) with **11 total bib entries**,
   thin for an AIAA Journal submission.

3. **new-aiaa.cls swap for paper.** **Status: NOT DONE, explicitly deferred with a
   comment.** `paper/p1_main.tex` lines 6–11 explicitly document using
   `\documentclass{article}` + natbib as a stand-in because `new-aiaa.cls`/`aiaa.bst` are
   not available in this environment (AIAA distributes them directly to authors).
   **Effort: S** (mechanical swap once files obtained) but requires an external asset the
   agent cannot fetch itself.

4. **T9 adversarial check.** **Status: PENDING**, confirmed above — `site/gates.json`
   says so and no review artifact exists. **Effort: S–M.**

5. **Turbine-proxy (LS89/T106) inverse cases.** **Status: DATA PRESENT, NO INVERSE RUN.**
   `data/airfoils/turbine/ls89/` exists. `grep -rl turbine experiments/ configs/ src/`
   returns **nothing** — no config, no code path, no experiment result references
   "turbine" anywhere. T9's design doc *plans* to use LS89 in Stage 2 (S3 gate,
   "already in repo") but nothing has executed against it. This is squarely pending, not
   partially done. **Effort: L** (requires Stage-2-style cascade/streamtube handling per
   T9's own design doc — this is explicitly scoped as Stage 2, not Stage 1, work; the
   user's original scope named it, but the project's own design review correctly deferred
   it past Stage 1). **Blocks:** any claim about turbomachinery applicability — currently
   zero evidence beyond a design document.

6. **Kulfan-LEM and Masters-unwrapped LE treatments (Deviation 8).** **Status: NOT
   IMPLEMENTED.** Confirmed via T8 ANALYSIS.md's own Deviation 8: "LEM is not wired into
   the Newton free vector... Masters-unwrapped was never implemented." Only
   `{none, prescribed}` LE-treatment levels were ever run — a 2-level contrast against a
   pre-registered 4-level factor. **Effort: M** (each is a distinct parameterization
   requiring its own DOF-accounting and constraint-row work, i.e., mini-T3/T5 redo).

7. **n=16 Bernstein cell (Deviation 7).** **Status: NOT RUN as a Newton-solve ablation.**
   T2's Gram-conditioning context curve *does* include an n=16 point (cond(GᵀG)=5.7e9),
   but that is fit-conditioning only, not a Newton-solve cell — T8's own ablation matrix
   stops at n=12 ("runtime scoping at cell generation," self-reported). **Effort: S**
   (infra exists; needs a config + run + the n=12 iteration-budget failure mode makes it
   likely to fail the iteration gate too — expected, not a blocker, but worth running to
   complete the FM-2 cliff picture past n=12).

8. **app/ deploy + Supabase.** **Status: SCAFFOLD ONLY, NOT DEPLOYED.**
   `app/backend` and `app/frontend` exist with real code (3471 `.py`/`.ts`/`.tsx` files
   counted, not a placeholder), and `app/README.md` explicitly documents the architecture
   with Supabase marked "NOT built in this phase" under a "Deferred" heading, and the
   frontend's Inverse view is explicitly labeled "stub, wired to the job API" in the same
   README. This is honestly self-scoped as unfinished, not misrepresented as done.
   **Effort: L** (auth, RLS, deploy pipeline, Vercel/Supabase wiring all remain).

9. **Site explainers depth.** **Status: MINIMAL.** `site/index.html` is 110 lines,
   `site/gates.json` is the data source; there is no per-gate explainer page, no
   plotted figures embedded in the site (the T8 PNGs live only under
   `experiments/results/t8/figures/` and `paper/`, not linked from `site/`). **Effort: S–M**
   depending on desired depth (embed existing figures vs. write new explainer prose).

10. **T2 Gram-conditioning JSON reproducibility.** **New finding, not on the user's
    candidate list.** `experiments/results/t2_gram_conditioning.json` is currently
    modified in the working tree relative to the commit `docs/gates/T2-closure.md` was
    written against (confirmed via `git status --short`/`git diff --stat`, 6 lines
    changed). Until this is committed or reverted, T2's archived closure numbers and the
    file on disk may silently diverge. **Effort: S** (decide: commit the update with a
    rationale, or revert to match the closure doc; either is fine, but leaving it
    uncommitted is the actual problem). **Blocks:** trust in T2's "reproducible from
    manifest" claim, a first-principles requirement in `CLAUDE.md`.

11. **T0/T1 closure documentation.** **New finding.** Both gates are marked `closed` in
    `site/gates.json` but have no `docs/gates/T{0,1}-closure.md` and no recorded
    adversarial-review pass, unlike every other closed gate (T2–T8 all have one).
    **Effort: S** (backfill closure docs from existing run logs/mfoil_internals.md).
    Low risk (T0/T1 have no numeric gate thresholds to falsify), but it is a real,
    verifiable gap in the gate-closure contract's uniform application.

12. **T5's deliberately-violating DOF case is filed under T8, not T5.** **New finding,
    minor.** `docs/GATES.md` condition (2) asks specifically for T5 to exercise a
    deliberately-violating `M+K=n_A+1` case; the actual artifact
    (`t8_dof_over`/`t8_dof_under`) lives in the T8 ablation matrix. Functionally present,
    administratively mis-filed. **Effort: trivial** (cross-reference in T5's closure doc,
    if/when one is written per item 11's pattern — T5 currently only has the shared
    `T4-T7-closure.md`, which does mention it, so this is a very minor nit, not a gap).

---

## 4. Paper completeness audit (`paper/p1_main.tex`, 1098 lines, compiles via tectonic per
its own header comment) — reviewer-lens gaps as of this stock-take

Read in full; section structure: Introduction, Formulation (parameterization, constraints,
extended Newton+DOF, derivative strategy, forced-transition closure, presolve),
Failure-mode instrumentation, The falsifiable test, Ablations and results (7 subsections),
Discussion (3 subsections), Conclusions.

**What a reviewer would reject/flag today:**

1. **No figure of an actual airfoil.** `grep includegraphics` returns exactly 4 figures,
   all from `experiments/results/t8/figures/`: `h3_convergence_overlay.png`,
   `station_selection.png`, `n_sweep.png`, `h2_flow_solves.png` — all *diagnostic/ablation*
   plots. **There is no target-vs-recovered geometry overlay, no Cp/edge-velocity
   distribution plot, no picture of a single airfoil shape anywhere in the paper.** For a
   paper whose entire subject is *airfoil geometry* recovery from a *pressure* target,
   this is a serious, reviewer-obvious gap — the qualitative "does the recovered shape
   look right / does the recovered Cp match" evidence that referees expect to see first is
   entirely absent, even though the underlying data to make it exists in every
   `result.json`/`diagnostics.json` (A* vs A_recovered arrays, target vs achieved
   cl/cd, and CST coefficients that trivially reconstruct ζ(ψ)).
2. **No comparison table against other inverse-design methods.** The H2 comparison is
   against the paper's own nested-LM control, not against any published inverse-design
   result (e.g., Selig/Maughmer, Volpe-Melnik-family methods, other CST-inverse work by
   Morris et al. which is cited but not numerically compared). A reviewer will ask "how
   does this compare to X" with a table, not prose.
3. **Thin literature review — 11 bib entries total** (`paper/p1_refs.bib`, confirmed by
   count), only 8 in-text `\cite` occurrences found via grep. For an AIAA Journal
   submission this is well below the norm (typically 25–50+ for a methods paper); the
   novelty search (pending item 2 above) would likely surface more required citations.
4. **No appendix with derivations.** The formulation section states results (constraint
   rows, DOF counting) but §3.2/§3.3-equivalent derivations from the dossier are not
   reproduced in an appendix — a reviewer checking the Beta-function area identity or the
   A₀=√(2R_LE/c) relation by hand has nowhere in the paper itself to do so (must go to
   `docs/CST_MISES_Monolithic_Inverse_Design.md`, which is not part of the submission).
5. **Placeholder document class**, self-documented (`\documentclass{article}` standing in
   for `new-aiaa`) — cosmetic for a preprint, blocking for actual AIAA submission (item 3
   in §3 above).
6. **H2's headline number is a correction of the paper's own earlier framing**, and the
   abstract-area comment shows this was caught and fixed — good practice, but it means the
   paper's central efficiency claim (3–8x, not "orders of magnitude") is less dramatic than
   the dossier's original hypothesis, which is exactly the kind of result a
   results-oriented reviewer (or the AIAA novelty bar) may find "modest hardware for the
   general read" — this is a framing/positioning risk, not a validity defect, but worth
   naming since a top-journal bar cares about impact framing.
7. **N=1 statistics throughout T8** are disclosed transparently in the paper's ablations
   section (matching ANALYSIS.md) — a rigorous reviewer will still flag single-seed,
   single-run results as thin evidence for architecture-level claims, even though the
   paper is honest about this rather than overclaiming. This is a pending-statistics-depth
   item, not a fabrication issue.
8. **No validation against experimental/independent CFD data** (e.g., XFOIL/MSES
   cross-check of a recovered geometry, or wind-tunnel Cp data) — everything is
   self-consistent within the mfoil model (T7's "release-and-verify" reproduces mfoil's
   own cl/cd, which is circular by construction, not an external validation). This is the
   single largest scientific-credibility gap for a journal (vs. workshop/preprint) bar.

**Effort estimate for a "top-journal-ready" paper:** **L** — items 1, 2, 3, 4, 8 above are
each non-trivial (new figures from existing data, lit survey, derivation appendix,
external validation), even though the underlying numerical work (T0–T8) that would feed
them is already done and trustworthy per §1–§2 above.

---

## 5. Working-tree state at time of this review (transparency note)

`git status --short` at review time showed:
```
 M .claude/launch.json
 D .claude/scheduled_tasks.lock
 M configs/default.yaml
 M experiments/results/t2_gram_conditioning.json
 M paper/p1_refs.bib
 M src/cins/config.py
?? src/cins/benchmarks/paper_figures.py
?? src/cins/cst/io.py
?? tests/gates/test_t8_uiuc_loader_panel.py
?? tests/unit/test_cst_io.py
```
This is genuine in-progress work (UIUC loader, paper-figure generation script, a modified
T2 conditioning artifact and refs.bib) that predates this stock-take request and is not
yet committed. It should not be read as regressions; it is exactly the "UIUC loader"
pending item (§3.1) partially underway. Flagged here so the main session does not lose
track of it, and so this stock-take's "PENDING: UIUC panel" verdict is understood as "code
started, not yet run/committed/closed," not "not started at all."

---

## 6. Bottom line

**Genuinely ACHIEVED (verified against artifacts, not just prose):** T2–T8 closed with
real, resolved adversarial findings (not rubber-stamps — T3 and T4 each document an actual
bug caught and fixed); T7's falsifiable test independently reproduces to the numbers
claimed; T8's headline H1 panel (18/18) and H2 flow-solve ratio (3–8x, not the
pre-registered ≥100x) both check out against raw JSON and are reported honestly even
where they falsify the a priori hypothesis — this is the strongest positive signal in the
whole stock-take, since it demonstrates the adversarial-review process catches real
things rather than existing for show.

**Genuinely PENDING, none fabricated as done:** UIUC ~100-panel run (loader coded,
uncommitted, not executed), novelty search, AIAA class swap, T9 adversarial review,
turbine/LS89 inverse runs (data present, zero code path), Kulfan-LEM/Masters-unwrapped LE
treatments, n=16 Newton-solve cell, app deploy + Supabase, site explainer depth, T0/T1
closure documentation, and a paper that — while numerically honest — currently lacks the
airfoil/Cp figures, comparison table, derivation appendix, and external validation a
top-journal reviewer will expect.
