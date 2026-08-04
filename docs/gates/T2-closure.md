# Gate closure report — T2: CST module

**Closed:** 2026-08-04 · **Branch:** main · **Owner:** t2-cst (python-pro) + main session

## Evidence
| Criterion | Threshold (configs/default.yaml) | Measured | Verdict |
|---|---|---|---|
| Fit RMS, NACA 2412 | < 1e-3 chord | 3.99e-5 | PASS |
| Fit RMS, NACA 0012 | < 1e-3 | 2.46e-5 | PASS |
| Fit RMS, NACA 23012 | < 1e-3 | 9.27e-5 | PASS |
| Fit RMS, NACA 4415 | < 1e-3 | 6.99e-5 | PASS |
| cond(GᵀG) vs n archived | — | experiments/results/t2_gram_conditioning.json | PASS |

FM-2 curve: 498 (n=4) → 7.3e3 (6) → 1.09e5 (8) → 1.63e6 (10) → 2.46e7 (12) → 5.72e9 (16);
cond(GᵀG) ≈ 4ⁿ growth, i.e. cond(M) ≈ 2ⁿ — consistent with dossier §4 FM-2.

## Reviews
- **Code review (feature-dev:code-reviewer):** 1 important — tautological cache test
  → rewritten to assert real cache-hit semantics (cache_info counters, bit-identical
  reuse). Note: adapter npanel hardcoded → now resolves from config. Note: Lednicer
  format risk in fit._split_surfaces → spawned background task (UIUC loader) before T8.
- **Aero-adversary:** genuine attack, **zero CONFIRMED findings**. Verified: CCW
  round-trip cl (0.0–2.5% vs vendor path over 5 cases), endpoint identities (6+ digits),
  complex-step columns vs dsurface_dA (2.8e-17), no lstsq truncation to n=32,
  conditioning JSON reproduces exactly from source. PLAUSIBLE (low): no truncation
  guard in fit_cst for n≳60 — latent, out of gate scope.

## Artifacts
- experiments/results/t2_gram_conditioning.json (manifest: git SHA, config hash, timestamp)
- tests/gates/test_t2_fit.py (pinned); 22+12+7 unit tests, hypothesis properties

## Sign-off
Tests ✅ · Domain validation ✅ · Adversarial review ✅ · Artifacts ✅ · Docs/site ✅ · Pushed ✅
