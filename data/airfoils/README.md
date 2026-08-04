# Validation geometry data

## uiuc/
123-section stratified sample of the UIUC Airfoil Coordinates Database
(https://m-selig.ae.illinois.edu/ads/coord_database.html), selected as every 13th
entry of the sorted file index (deterministic, seed-free; see SAMPLE_LIST.txt).
Downloaded 2026-08-04. Mixed formats (Selig / Lednicer) — the loader in
`cins.cst.fit` must handle both. Used for the T2 fit sweep and T8 panel.

## turbine/ls89/
VKI LS89 high-pressure turbine nozzle vane (transonic cascade benchmark).
- `LS89.p3d` — multi-block Plot3D mesh from https://github.com/pavanakumar/LS89
- `ls89_profile_raw_m.dat` — blade surface extracted from block 0, j=0 boundary
  (closed 350-pt loop, meters). Extracted true chord 68.42 mm vs published 67.647 mm
  (mesh-discrete extreme-point measure).
- `ls89_profile_chordnorm.dat` — chord-normalized, LE-extreme at origin, unrotated.
- `mur43..mur49/pressureDistribution.dat` — experimental isentropic Mach/pressure
  distributions (MUR test conditions) — Stage 2 validation anchors.
Role in Stage 1: the "hard geometry" case for the T2 CST fit gate (high camber,
high turning; exercises FM-2/FM-3 harder than NACA sections).

## Deferred
- T106 LP turbine profile: canonical geometry is an IGES at the Cambridge Whittle
  Lab site; no clean public .dat located yet. Acquire during T8 panel assembly
  (or substitute a second UIUC high-camber section).
