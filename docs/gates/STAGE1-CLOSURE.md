# Stage 1 — FINAL CLOSURE review (adversarial)

**Date:** 2026-08-05 · **Reviewer stance:** adversarial (attack, do not approve) ·
**Repo HEAD at start of review:** `d876fe1`. **Repo HEAD moved during this review to
`ea53a4e`** (a concurrent process — visible in `ps aux` as a separate zsh job launched
11:09am running `app/backend` tests + ruff + `git commit` + `git push origin main` —
committed and pushed to `main` while this closure review was in progress). This is logged
as **Finding CL-0** below; it means "the state I reviewed" and "the state now on `main`"
are not the same commit, which is itself a violation of the spirit of a "final closure"
review (main should be frozen while the closing adversarial pass runs). All findings
below are pinned to the artifacts as I read them; re-verify after the concurrent writer
stops.

Method: every verdict below is checked against a live command I ran in this session
(pytest, ruff, tectonic, grep, direct file reads, `ps aux`), not against the stock-take's
prose. Where the stock-take (`docs/gates/STAGE1-STOCKTAKE.md`, dated 2026-08-04) already
established a fact and nothing changed, I say so and move on; where something changed
since, I re-verified from scratch.

---

## CL-0 — Concurrent uncoordinated write to `main` during the closure review (PROCESS finding)

**Defect:** a second, uncoordinated process was actively running the test suite, ruff,
and `git commit && git push origin main` against this exact repo while this adversarial
closure review was being conducted, moving `HEAD` from `d876fe1` to `ea53a4e` mid-review.
**Evidence:** `ps aux` (this session) shows PID 6264 running a compound shell command
(`git commit -q -m "Showcase replay: plot the combined extended-system residual..." &&
git push -q origin main`) at 11:09am; `git log -1` before vs. after this review's start
shows the head commit changed. **Classification: CONFIRMED.** This does not invalidate
any individual gate's evidence (each finding below is checked against files as read at
the time), but it means the user's "final closure" cannot be certified against a single
pinned commit unless the concurrent writer is stopped first — re-run `git log -1` and
diff against `ea53a4e` before treating this report as authoritative for whatever commit
is on `main` when the user reads it.

---

## 1. UIUC loader + panel (H1 Wilson certification) — **TRACKED-OPEN, one CONFIRMED gap**

- Loader (`src/cins/cst/io.py`) and its unit tests (`tests/unit/test_cst_io.py`, 15
  tests) and corpus-sweep gate (`tests/gates/test_t8_uiuc_loader_panel.py`) are now
  **committed** (verified `git log -1 -- src/cins/cst/io.py` → `b96190d`, `git status
  --short` shows no untracked/modified state on these three files) — this closes the
  stock-take's item 10-style "uncommitted work" concern for the loader specifically.
- **CONFIRMED FINDING (fix-before-closure candidate): the min-TE-gap fix has no
  regression test.** `src/cins/cst/io.py:239-274` adds `_ensure_min_te_gap`/`MIN_TE_GAP`
  specifically to fix a measured failure (comment at `io.py:230-236` cites "63/117 UIUC
  panel cells" killed by `mfoil.py:748`'s `assert t[0] > 0`). I grepped the entire test
  tree (`grep -rln "ensure_min_te_gap\|MIN_TE_GAP" tests/ src/` → only `src/cins/cst/io.py`
  itself matches) — **zero tests reference this function or constant by name**, and no
  test in `test_cst_io.py` asserts a post-load TE gap ≥ `MIN_TE_GAP` on a known
  sharp-TE fixture (e.g. a synthetic file with coincident TE endpoints), nor does any
  test assert the claimed before/after viscous-solve-success-rate improvement the
  comment cites as the fix's justification. A regression here (e.g. someone "simplifying"
  `_ensure_min_te_gap`'s displacement-direction logic) would silently reopen the
  63/117-cell failure mode with the existing test suite staying green. **Fix:** add a
  unit test asserting `hypot(*(X[:,-1]-X[:,0])) >= MIN_TE_GAP` after load for a
  synthetic sharp-TE fixture, and ideally one for a real corpus file known to need
  opening.
- Panel machinery: 117 cell configs exist (`configs/experiments/panel_uiuc/*.yaml`,
  counted). First pass produced 117 result dirs (`experiments/results/t8/panel_uiuc_*`,
  all currently untracked — expected, matches the task's framing). 86 cells that failed
  the first pass are being individually re-run post-TE-gap-fix via
  `scratchpad/uiuc_rerun.sh`, which — unlike the earlier `panel_uiuc_sweep.log` run,
  which **crashed the whole sweep** on an uncaught `AssertionError: stagpoint_move:
  velocity error` after only 30/117 cells (visible in `panel_uiuc_sweep.log`, a real
  robustness gap in the batch-sweep path, not just a per-airfoil physics failure) —
  correctly isolates each cell in its own subprocess so one crash doesn't kill the run.
  **Confirmed live and progressing** (`ps aux` shows the subprocess actively solving
  `panel_uiuc_fx69h083` at review time, one cell has been running >12 minutes, worth
  watching for a hang but not yet a failure); **34 converged / 6 non-converged / 25
  attempted-so-far of 86**, i.e. genuinely in progress, not stalled or abandoned.
  Per the task instruction, this is reported as **properly-tracked-in-progress**, not
  waited on.
- **New observation, not previously flagged:** even with the TE-gap fix applied, the
  wake-direction assertion (`mfoil.py:748`) still fires on some cells in the rerun
  (e.g. `ah81131`, `e182` in `uiuc_rerun.log`) — the fix reduces but does not eliminate
  this failure mode, meaning the eventual Wilson-CI panel denominator will legitimately
  exclude some sections for a still-not-fully-characterized reason (orientation/topology
  edge cases beyond thin TE gaps). Worth a named skip-list entry with a *diagnosed*
  reason once the rerun finishes, not just an aggregate pass/fail count — currently
  tracked correctly as open, not mis-stated as closed.

## 2. Paper (`paper/p1_main.tex`, now 1737 lines / 21 bib entries) — **substantially
improved since stock-take; CLOSED for the "does the promised content exist" bar,
one editorial nit**

- **Figures:** `grep includegraphics` returns **8** references (up from 4 at
  stock-take): the 4 original ablation/diagnostic plots plus 4 new evidence figures —
  `fig_t7_geometry_overlay.png`, `fig_t7_cp_comparison.png`, `fig_t7_flow_solution.png`,
  `fig_h1_panel_gallery.png`. I verified these are **not** missing (my first grep for
  them under `paper/` at repo root was a false negative from not accounting for
  `\graphicspath{{../experiments/results/t8/figures/}}`); the actual files exist at
  `experiments/results/t8/figures/paper/fig_t7_*.png` and `fig_h1_panel_gallery.png`
  (all present, non-trivial file sizes). **This closes stock-take gap #1** (no airfoil
  geometry / Cp figure) — the paper now has target-vs-recovered geometry overlays and
  Cp comparison plots, addressing the single most reviewer-obvious gap identified
  previously.
- **Comparison table:** `tab:comparison` (paper/p1_main.tex:1314-1391) exists, compares
  6 method classes, and is disciplined about sourcing — rows (i)/(ii) are the paper's
  own measured numbers, rows (iii)-(vi) are explicitly labeled `qual.` wherever the
  cited source doesn't report a directly comparable number, and every non-`qual.` claim
  carries a `\citep{}`. Spot-checked 3 bib entries (`yilmaz2020cgan`, `yu2025cddpm`,
  `lfpinn2024`) — plausible, specific (DOI/venue/volume/pages), not obviously
  fabricated placeholders. **Closes stock-take gap #2.**
- **Appendices A-D present:** Beta-function area-row derivation, DOF accounting worked
  example (T7 config), onset-closure Jacobian rows, reproducibility statement
  (`paper/p1_main.tex:1551-1737`). **Closes stock-take gap #4.**
- **UIUC placeholder honestly marked:** `% PLACEHOLDER-UIUC-PANEL` appears 3 times
  (lines 1186, 1461, 1548) explicitly noting the NACA half of H1 is done and the UIUC
  extension is pending — not silently omitted or overclaimed.
- **Novelty-search TODOs present and explicit:** lines 85, 276, 280 — "TODO before
  submission: confirm via AIAA/ASME digital library search," "no published work is
  known to couple a Newton- ... Confirm before claiming novelty in the submitted
  version." Honest, not a silent gap.
- **Bib count: 21 entries** (up from 11), still thin for an AIAA Journal submission but
  materially better; the novelty-search TODO correctly flags this as pending, not
  resolved.
- **Compiles cleanly via tectonic:** `tectonic p1_main.tex` in this session produced
  `p1_main.pdf` (1.25 MiB) with only underfull/overfull hbox warnings and duplicate
  PDF-object-name warnings (typical multi-run artifacts, not errors) — **zero
  compilation errors**. Confirmed and then removed the built PDF (not a repo artifact
  to leave lying around).
- **Remaining true gaps (already honestly tracked, not new):** `new-aiaa.cls` swap
  still deferred (external asset, `p1_main.tex:6-11`), no external CFD/experimental
  validation beyond mfoil self-consistency (stock-take gap #8, unchanged — still the
  single largest scientific-credibility gap for a journal bar, not addressed by this
  round of figure/table additions since none of the new figures are *external*
  validation, they are still internal T7/T8 artifacts).

## 3. T9 (Stage 2 design review) — **adversarial check performed now; does NOT
survive cleanly — one CONFIRMED contradiction, two PLAUSIBLE gaps. T9 should NOT be
marked closed yet.**

I attacked `docs/T9-stage2-design-review.md` against its own stated validation ladder
and the dossier (`docs/CST_MISES_Monolithic_Inverse_Design.md` §8).

- **CONFIRMED: the S3 LS89 validation plan contradicts its own compressibility-scope
  decision, using data actually present in the repo.** T9's decision table states
  "Compressibility: Accept subcritical (Kármán–Tsien) for Stage 2; transonic deferred
  to MISES (Stage 3)" and its own work-breakdown item **S3** is "Viscous cascade + LS89
  subcritical cases (MUR conditions **below drag rise**)." I read the actual LS89 data
  shipped in this repo (`data/airfoils/turbine/ls89/mur43` through `mur49`,
  `pressureDistribution.dat`) and computed the peak isentropic Mach number reported in
  each file directly:
  ```
  mur43: max M_is = 0.964     mur44: max M_is = 0.964     mur45: max M_is = 1.022
  mur46: max M_is = 1.028     mur47: max M_is = 1.216     mur48: max M_is = 1.227
  mur49: max M_is = 1.225
  ```
  **Every single one of the seven MUR datasets actually present in this repository is
  transonic-to-supersonic locally (peak isentropic Mach 0.96-1.23), i.e. exactly the
  "transonic turbine cascades" regime the dossier itself says Kármán-Tsien is
  "inadequate" for** (dossier §8.5: "Kármán–Tsien is subcritical only. For transonic
  turbine cascades this is inadequate, and there is no cheap fix within a panel
  method"). T9's S3 gate description ("MUR conditions below drag rise") presumes a
  subcritical MUR case exists to validate against; **as scoped against the data actually
  in the repo, none does.** Either T9 needs to (a) name which MUR case it actually means
  and show it is genuinely subcritical (none of the 7 present qualify), (b) acquire a
  lower-loading MUR case that is genuinely subcritical, or (c) admit S3 as currently
  written cannot be executed with the data in hand and needs re-scoping (e.g. Kármán-
  Tsien pushed to its validity edge only, or accept it as a stress-test/negative-result
  case rather than a validation case). **This is a load-bearing planning defect, not a
  cosmetic one** — it is exactly the kind of thing that would surface as "why did S3
  fail" three weeks into Stage 2 rather than being caught now. **CONFIRMED, blocks
  clean T9 closure.**
- **PLAUSIBLE: the periodic-kernel decision does not address the self-panel (own-panel)
  singular integral.** Dossier §8.2 (which T9 adopts verbatim) says "the panel-integrated
  influence coefficients must be re-derived with the new kernel — either analytically or
  by adaptive quadrature. Quadrature is the safer first implementation." The `ln(z-z0)
  → ln[sin(π(z-z0)/s)]` kernel retains the same **logarithmic singularity at z=z0**
  (the panel's self-induction term) as the isolated-airfoil kernel it replaces — generic
  adaptive quadrature (e.g. naive Gauss rules) does not integrate a log singularity to
  machine precision without a substitution or a known closed-form treatment for the
  singular sub-interval, which is exactly why mfoil's own isolated-airfoil linear-
  vorticity panel method almost certainly has *analytic* self-panel integrals already
  (not verified in this pass — would require reading `vendor/mfoil.py`'s panel-influence
  routines, out of scope for this review but flagged for whoever implements S0). Neither
  the dossier nor T9's adoption of it says how the self-panel term is to be handled for
  the new kernel; "adaptive quadrature" as stated is only safe for the *off-diagonal*
  (non-self) panel pairs. **PLAUSIBLE, not demonstrated in this session** (I did not
  attempt to implement or numerically test the kernel), but a real, specific,
  falsifiable risk that the design doc's risk list does not name.
- **PLAUSIBLE: the "s=10^6 reproduces Stage 1 exactly" oracle risks catastrophic
  cancellation, not exactness.** As `s → ∞`, `sin(π(z-z0)/s) → π(z-z0)/s`, so the ratio
  `ln[sin(π(z-z0)/s)] / ln(z-z0)` involves a near-linear regime where floating-point
  cancellation in `sin` of a very small argument, combined with summing many panels'
  periodic images, could plausibly produce agreement at only 1e-8-1e-10 relative, not
  bit-exact — which may or may not be "exactly" in the sense the regression gate needs
  (T7's own bar is 1e-11). This is a numerics risk the design doc doesn't discuss and
  the risk list (branch cuts, stagnation tracking, trip-onset) doesn't mention.
  **PLAUSIBLE**, not demonstrated (no cascade kernel code exists yet to test against).
- The DOF re-assertion plan itself (inlet prescribed / outlet free / Kutta row) is
  correctly flagged in the doc as "must be re-asserted" (i.e., explicitly deferred to
  implementation, not falsely claimed as already done) — this is honest scoping, not a
  gap.
- **Verdict: T9 does NOT survive this adversarial pass cleanly.** The CONFIRMED LS89/
  Kármán-Tsien contradiction is real and load-bearing (it would derail S3 as currently
  planned) and should be fixed in the design doc (either re-scope S3's premise or name
  a genuinely subcritical case) before `site/gates.json`'s T9 entry is moved from
  `in_progress` to `closed`. **`site/gates.json`'s current `"status": "in_progress"`
  for T9 remains the CORRECT state — do not close T9 on this pass.**

## 4. App (deploy readiness) — **TRACKED-OPEN: functionally sound, documentation stale
against actual deployment; one CONFIRMED doc gap**

- Backend tests: `.venv/bin/python -m pytest app/backend/tests -q` → **38 passed, 0
  failed** (fresh run this session, includes `test_showcase.py` — the "v3 stage
  capture" test file the task asked me to confirm — present and passing).
- Frontend build: `npm run build` (Next.js 16.3.0 / Turbopack, `app/frontend`) →
  **compiles successfully**, TypeScript check passes, all 6 routes statically
  generated (`/`, `/analyze`, `/flowfield`, `/gallery`, `/inverse`, `/_not-found`).
  No build errors.
- **CONFIRMED FINDING: `app/README.md` does not document the free-tier latency issue,
  and is stale relative to the actual public deployment.** I grepped
  `app/README.md`/`app/frontend/README.md`/`app/frontend/CLAUDE.md` for
  `latency|cold start|166|render.com|onrender|free tier|free-tier` — **zero matches**.
  `app/README.md`'s own "Deploy" section (line 273 onward) references deploying the
  frontend against "the deployed backend's origin (e.g. the **HF Space** URL)" — Hugging
  Face Spaces, not Render — which does not match the task's stated actual deployment
  (`https://cins-backend.onrender.com`, Render free tier). The README is written for an
  earlier/different deployment target and has not been updated to reflect (a) the actual
  Render + Vercel URLs now live, or (b) the measured ~166s viscous-solve latency on
  Render's free tier that is the single biggest known UX problem with the live app.
  A user reading `app/README.md` today would not learn the app is deployed, where, or
  that first-request latency is a known, expected, multi-minute wait. **Fix:** add a
  "Live deployment" section naming both URLs, the free-tier cold-start/166s-solve
  caveat, and correct or remove the stale HF Space reference.

## 5. LS89/turbine data — **confirmed still unused by any code path; correctly tracked
as post-rerun/Stage-2 scope, but see CL-3's T9 finding above which affects its own
future plan**

`grep -rln "turbine|ls89|LS89" src/ configs/ experiments/results/` → **zero matches**
excluding data files themselves. No config, no pipeline, no experiment result
references LS89 anywhere in code. This matches the stock-take exactly (nothing new).
Correctly classified as pending, not fabricated as done — but see §3 above: the plan
that would eventually consume this data (T9 §S3) currently has a data/physics mismatch
that should be fixed before anyone starts writing that code path, or the first attempt
will discover the same contradiction the hard way.

## 6. TODO/FIXME/PLACEHOLDER sweep + `site/gates.json` cross-check

`grep -rn "TODO\|FIXME\|PLACEHOLDER\|XXX(" docs/ src/ tests/ configs/` (excluding
`paper/`, which is separately audited in §2) → **zero matches**. No untracked
TODO/FIXME/PLACEHOLDER markers outside the paper and the already-known
`docs/T9-stage2-design-review.md` pending-review marker.

`site/gates.json` T9 entry: `"status": "in_progress"`, evidence text: "...Adversarial
check pending." — **this review is that pending adversarial check, and per §3 above it
does NOT pass cleanly**, so `in_progress` remains the *correct* state, not merely the
previously-correct-but-now-stale state. Do not flip T9 to `closed` off the back of this
review; flip it only after CL-3's LS89/Kármán-Tsien contradiction is resolved in the
design doc itself.

## 7. Full test suite + ruff — **CLOSED, green**

- `.venv/bin/python -m pytest tests/ -q` — run twice in this session (two independent
  background invocations, both exit code 0), consistent result: dot-pattern shows
  **zero `F`/`E` markers, exactly one `s` (skip)**, matching the stock-take's
  characterization exactly (the documented UIUC-corpus-adjacent skip). No new failures
  introduced since stock-take.
- `.venv/bin/ruff check src/ tests/` → **"All checks passed!"**
- `.venv/bin/python -m pytest app/backend/tests -q` → **38 passed**, 0 failed (see §4).
- `npm run build` in `app/frontend` → clean (see §4).

---

## Overall Stage 1 verdict

**Not yet cleanly closeable as "Stage 1 done" in one shot.** The core science (T0-T8)
remains as strongly evidenced as the 2026-08-04 stock-take found — nothing in this
session's re-checks contradicts that; T7/T8's numbers were not re-derived again here
(no reason to, nothing changed) but the surrounding infrastructure (paper, app, loader)
that stock-take flagged as pending has **materially progressed**, most of it well:

**Genuinely CLOSED since the stock-take:**
- UIUC loader code + its own unit/gate tests (committed, not just written).
- Paper: airfoil/Cp geometry figures, comparison table, appendices A-D, thicker
  bibliography (21 vs 11) — closes 3 of the stock-take's 4 major paper gaps
  (figures, comparison table, appendix derivations); compiles cleanly.
- Full test suite + ruff + app backend tests + frontend build all green.

**Still TRACKED-OPEN, honestly so (not fabricated as done):**
- UIUC ~100-panel Wilson-CI run (in progress, actively running, 34/86 converged so far
  of the rerun batch — do not wait, monitor).
- T9 — correctly still `in_progress`; this review's adversarial pass surfaced a real
  (CONFIRMED) contradiction in the S3/LS89 plan that should be fixed in the design doc.
- External validation for the paper (still the largest scientific-credibility gap).
- `new-aiaa.cls`, novelty search, app deploy docs (see CL-4).
- LS89 code path (zero, correctly scoped to post-rerun/Stage 2).

**New CONFIRMED findings from this pass (fix-before-final-closure):**
1. **CL-0** — a concurrent process committed and pushed to `main` during this closure
   review; re-verify against current `HEAD` before treating any verdict here as final.
2. **§1** — the UIUC loader's min-TE-gap fix (`_ensure_min_te_gap`/`MIN_TE_GAP`,
   `src/cins/cst/io.py:239-274`) has no regression test; a future refactor could silently
   reopen the 63/117-cell failure it was written to fix with the suite staying green.
3. **§3** — T9's S3 gate ("LS89 subcritical cases, MUR conditions below drag rise")
   contradicts the actual LS89 data shipped in the repo: all 7 available MUR datasets
   (mur43-49) are transonic-to-supersonic locally (peak isentropic Mach 0.96-1.23), not
   subcritical, directly conflicting with T9's own "Kármán-Tsien, subcritical only"
   compressibility scope decision for Stage 2. This should be fixed in
   `docs/T9-stage2-design-review.md` before T9 is marked closed.
4. **§4** — `app/README.md` does not document the free-tier latency issue and still
   references a stale (Hugging Face Space) deployment target inconsistent with the
   actual Render/Vercel deployment.

None of these four are science-blocking (T0-T8's numeric gates are untouched and remain
independently verified), but items 2-4 are exactly the class of finding a "final
closure" adversarial pass exists to catch before the label is applied, and CL-0 means
the user should re-run `git log -1` before accepting this report's snapshot as current.


---

## Remediation addendum (main session, 2026-08-05, commit-pinned)

All four CONFIRMED findings resolved:
- **CL-0**: closure pinned to the frozen commit recorded below (the mid-review HEAD
  movement was this session's own deploy/E2E fixes, now quiesced).
- **TE-gap regression**: `tests/unit/test_cst_io.py` now pins `_ensure_min_te_gap`
  by name (sharp-TE open, duplicate collapse, flat-back untouched) — suite green.
- **T9/LS89 scope**: T9 amended — MUR pressure comparisons moved to Stage 3; LS89
  geometry-side checks only in Stage 2; Gostelow is THE Stage 2 gate. With the
  amendment the adversarial check passes; T9 CLOSED on the board.
- **app/README**: live URLs + measured free-tier latency + CORS lesson documented.

**Stage 1 verdict: CLOSED** at the pinned commit, with two honestly-tracked
follow-ons that do not gate Stage 1: (a) the UIUC 87-cell rerun completing in the
background (its summary + ANALYSIS/H1 update land as a follow-up commit — panel
machinery itself is verified), (b) the paper's pre-submission novelty search
(TODO-marked in the manuscript, required before submission, not before closure).


## UIUC panel closed (2026-08-05)

The follow-on tracked at closure is complete. The 117-section UIUC
panel ran to completion after the loader trailing-edge-gap fix.

Coefficient accuracy holds on every converged section: 83 of 83,
Wilson 95 percent lower bound 0.956. The composite
pre-registered criterion is not met, at 0.880 with lower bound
0.792, because ten sections needed between 10 and 50
Newton iterations while still recovering coefficients to between 1e-11 and
3e-10. The single-digit iteration expectation was calibrated on NACA sections
and does not transfer to the wider UIUC geometry space.

Full stratification, exclusion classes and per-cell records are in
`experiments/results/t8/ANALYSIS.md` and
`experiments/results/t8/uiuc_panel_summary.json`.

Open item carried forward: three sections (goe780, mh62, naca64206) fail the
vendor wake-direction assertion for a reason unrelated to sharp trailing edges,
since their gap already exceeds the enforced minimum.

The pre-submission novelty search is also complete, recorded in
`docs/novelty-search.md`, and corrected a misattribution of the nearest prior
art that had propagated from the dossier into the manuscript.
