"""Loader for UIUC-style airfoil ``.dat`` coordinate files.

The UIUC Airfoil Coordinates Database ships two point-list conventions:

- **Selig**: a single continuous loop, one title line followed by
  TE(upper) -> ... -> LE -> ... -> TE(lower), i.e. the reverse of mfoil's
  own CCW convention (see ``src/cins/CLAUDE.md`` and
  ``tests/unit/test_cst_fit.py::test_fit_cst_handles_selig_ordering``).
- **Lednicer**: a title line, then a "point count" line
  (``n_upper n_lower``, both values necessarily > 1 -- a chord-normalized
  coordinate can never exceed 1 -- which is exactly how this format is told
  apart from Selig without any external metadata), then the upper surface
  LE -> TE and the lower surface LE -> TE as two blank-line-separated
  blocks.

``load_airfoil_dat`` normalizes both into a single (2, N) CCW ndarray in
mfoil's own convention -- **TE-lower -> LE -> TE-upper** -- chord-normalized
to [0, 1], ready to feed straight into ``cins.cst.fit.fit_cst`` or
``cins.solver.mfoil_adapter.make_mfoil(coords=...)``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "AirfoilParseError",
    "load_airfoil_dat",
    "detect_format",
    "UIUC_DIR",
    "uiuc_dat_path",
]

UIUC_DIR = Path(__file__).resolve().parents[3] / "data" / "airfoils" / "uiuc"


def uiuc_dat_path(name: str) -> Path:
    """Resolve a bare UIUC section name (e.g. ``"ag16"`` or ``"ag16.dat"``) to
    its ``.dat`` path under ``data/airfoils/uiuc/``. Does not check existence
    (callers decide whether a missing file is a hard error or a skip)."""
    stem = name[:-4] if name.endswith(".dat") else name
    return UIUC_DIR / f"{stem}.dat"


class AirfoilParseError(ValueError):
    """Raised when a ``.dat`` file cannot be parsed into a valid closed section."""


def _read_nonblank(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(errors="replace").splitlines()
    return [(i, line) for i, line in enumerate(text) if line.strip()]


def _parse_xy(line: str) -> tuple[float, float] | None:
    toks = line.split()
    if len(toks) < 2:
        return None
    try:
        return float(toks[0]), float(toks[1])
    except ValueError:
        return None


def _is_lednicer_count_line(line: str) -> tuple[int, int] | None:
    """A Lednicer point-count line is exactly two tokens, both > 1.

    Chord-normalized coordinate pairs (Selig's first data row) are always
    <= ~1 in magnitude, so "both values strictly greater than 1" is an
    unambiguous discriminator requiring no external format metadata.
    """
    toks = line.split()
    if len(toks) != 2:
        return None
    try:
        a, b = float(toks[0]), float(toks[1])
    except ValueError:
        return None
    if a > 1.0 and b > 1.0 and a == int(a) and b == int(b):
        return int(a), int(b)
    return None


def detect_format(path: str | Path) -> str:
    """Return ``"lednicer"`` or ``"selig"`` for the given ``.dat`` file."""
    path = Path(path)
    nonblank = _read_nonblank(path)
    if len(nonblank) < 2:
        raise AirfoilParseError(f"{path}: file has no data lines")
    # nonblank[0] is the title line; the next non-blank line is either the
    # Lednicer point-count line or the first Selig coordinate pair.
    second_line = nonblank[1][1].strip()
    return "lednicer" if _is_lednicer_count_line(second_line) is not None else "selig"


def _load_lednicer(path: Path) -> NDArray:
    nonblank = _read_nonblank(path)
    second_idx, second_line = nonblank[1]
    counts = _is_lednicer_count_line(second_line.strip())
    if counts is None:
        raise AirfoilParseError(f"{path}: expected a Lednicer point-count line")
    n_upper, n_lower = counts

    # Blocks are separated by blank line(s) in the ORIGINAL file (not the
    # pre-filtered nonblank list), so re-split on the raw text after the
    # count line.
    raw_lines = path.read_text(errors="replace").splitlines()
    data_lines = raw_lines[second_idx + 1 :]
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in data_lines:
        if line.strip() == "":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)

    if len(blocks) != 2:
        raise AirfoilParseError(
            f"{path}: Lednicer format expects 2 blank-line-separated blocks, found {len(blocks)}"
        )

    def _parse_block(lines: list[str]) -> NDArray:
        pts = []
        for line in lines:
            xy = _parse_xy(line)
            if xy is None:
                raise AirfoilParseError(f"{path}: unparseable coordinate line {line!r}")
            pts.append(xy)
        return np.array(pts, dtype=float).T  # (2, n)

    upper = _parse_block(blocks[0])  # LE -> TE
    lower = _parse_block(blocks[1])  # LE -> TE

    if upper.shape[1] != n_upper or lower.shape[1] != n_lower:
        raise AirfoilParseError(
            f"{path}: declared counts ({n_upper}, {n_lower}) do not match parsed "
            f"block sizes ({upper.shape[1]}, {lower.shape[1]})"
        )
    if upper.shape[1] < 2 or lower.shape[1] < 2:
        raise AirfoilParseError(f"{path}: surface block too short to define a section")

    # Stitch to mfoil's TE-lower -> LE -> TE-upper convention: reversed
    # lower (TE -> LE) followed by upper (LE -> TE), collapsing the shared
    # LE point (declared once in each block by the format) rather than an
    # argmin(x) split -- the format already tells us where LE is.
    lower_rev = lower[:, ::-1]  # TE -> LE
    le_lower, le_upper = lower_rev[:, -1], upper[:, 0]
    if not np.allclose(le_lower, le_upper, atol=1e-6):
        raise AirfoilParseError(
            f"{path}: upper/lower blocks disagree on the shared LE point "
            f"({le_lower} vs {le_upper})"
        )
    return np.concatenate([lower_rev[:, :-1], upper], axis=1)


def _load_selig(path: Path) -> NDArray:
    nonblank = _read_nonblank(path)
    pts = []
    for _, line in nonblank[1:]:
        xy = _parse_xy(line)
        if xy is None:
            raise AirfoilParseError(f"{path}: unparseable coordinate line {line!r}")
        pts.append(xy)
    if len(pts) < 4:
        raise AirfoilParseError(f"{path}: too few coordinate points ({len(pts)})")
    X = np.array(pts, dtype=float).T  # (2, n), TE-upper -> LE -> TE-lower

    # Selig order is the reverse of mfoil's CCW convention (fit.py /
    # test_cst_fit.py::test_fit_cst_handles_selig_ordering document this
    # exact relationship): flip to get TE-lower -> LE -> TE-upper.
    return X[:, ::-1]


def _normalize_chord(X: NDArray) -> NDArray:
    x0 = float(X[0].min())
    chord = float(X[0].max() - x0)
    if chord <= 0.0:
        raise AirfoilParseError("degenerate section: zero or negative chord")
    out = X.copy()
    out[0] = (out[0] - x0) / chord
    out[1] = out[1] / chord
    return out


def _fix_orientation(X: NDArray) -> NDArray:
    """Match mfoil's own CCW criterion exactly (its own shoelace sign, not a
    textbook convention) -- the identical formula used by
    ``cins.solver.mfoil_adapter._set_coords_fixed`` so a loaded section
    orients the same way a native mfoil NACA section does.
    """
    area = np.sum(X[0, :-1] * X[1, 1:] - X[0, 1:] * X[1, :-1])
    if area > 0:
        return X[:, ::-1]
    return X


def load_airfoil_dat(path: str | Path) -> NDArray:
    """Load a UIUC ``.dat`` airfoil coordinate file into a (2, N) CCW ndarray.

    Auto-detects Selig vs. Lednicer point-list convention (``detect_format``).
    Output is chord-normalized to [0, 1], oriented per mfoil's own CCW
    convention (TE-lower -> LE -> TE-upper), and directly usable by
    ``cins.cst.fit.fit_cst`` and
    ``cins.solver.mfoil_adapter.make_mfoil(coords=...)``.

    Raises ``AirfoilParseError`` for files that cannot be parsed into a
    plausible closed section -- callers doing a corpus sweep should catch
    this and record an explicit skip-list entry rather than silently
    dropping the file.
    """
    path = Path(path)
    if not path.exists():
        raise AirfoilParseError(f"{path}: file not found")

    fmt = detect_format(path)
    X = _load_lednicer(path) if fmt == "lednicer" else _load_selig(path)

    if X.shape[1] < 4:
        raise AirfoilParseError(f"{path}: too few points after parsing ({X.shape[1]})")
    if not np.all(np.isfinite(X)):
        raise AirfoilParseError(f"{path}: non-finite coordinates")

    X = _normalize_chord(X)
    X = _fix_orientation(X)
    X = _ensure_min_te_gap(X)
    return np.ascontiguousarray(X, dtype=np.float64)


# Minimum trailing-edge gap, in chords. Sharp-TE sections (duplicated or
# coincident endpoints — common in the UIUC corpus) make mfoil's build_wake
# TE-tangent sign test (`assert t[0] > 0`, mfoil.py:748) evaluate on numerical
# noise: the wake-direction connector n = x_last − x_first is ~0 and its sign
# is arbitrary, killing ~half of viscous solves (observed: 63/117 UIUC panel
# cells, 2026-08-05). Opening the TE to a small finite gap is the standard
# panel-code remedy (XFOIL's TGAP); 2e-4 c is well under fit/gate tolerances.
MIN_TE_GAP = 2.0e-4


def _ensure_min_te_gap(X: NDArray, min_gap: float = MIN_TE_GAP) -> NDArray:
    """Open a sharp/near-sharp trailing edge to a minimum finite gap.

    The loop convention is TE-lower (first column) -> LE -> TE-upper (last).
    If the endpoints coincide (duplicated sharp-TE point) the duplicate is
    dropped first; then, if the remaining gap is below ``min_gap``, both TE
    endpoints are displaced symmetrically along the local thickness direction
    (approximated by the mean of the two TE panel normals) to reach it.
    """
    if np.hypot(*(X[:, -1] - X[:, 0])) < 1e-12 and X.shape[1] > 4:
        X = X[:, :-1]  # drop exact duplicate closing point
    gap_vec = X[:, -1] - X[:, 0]
    gap = float(np.hypot(*gap_vec))
    if gap >= min_gap:
        return X
    # local thickness direction: perpendicular to the mean TE tangent
    t_lo = X[:, 0] - X[:, 1]
    t_up = X[:, -1] - X[:, -2]
    t_mean = t_lo / (np.hypot(*t_lo) or 1.0) + t_up / (np.hypot(*t_up) or 1.0)
    nrm = np.hypot(*t_mean)
    if nrm < 1e-12:
        d = np.array([0.0, 1.0])  # degenerate: open vertically
    else:
        t_mean /= nrm
        d = np.array([-t_mean[1], t_mean[0]])
        if d[1] < 0:
            d = -d  # +d points toward the upper surface
    need = 0.5 * (min_gap - gap)
    X = X.copy()
    X[:, 0] -= need * d   # lower TE point moves down
    X[:, -1] += need * d  # upper TE point moves up
    return X
