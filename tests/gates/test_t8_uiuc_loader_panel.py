"""Gate: UIUC .dat corpus loader sweep (STATS_PROTOCOL §3.3 panel prerequisite).

Every file under ``data/airfoils/uiuc/*.dat`` must parse to a plausible
closed section via ``cins.cst.io.load_airfoil_dat`` -- x/c within
``gates.io_x_range``, positive thickness, no NaN. Files that legitimately
fail get an explicit, reasoned skip-list entry (``KNOWN_BAD_UIUC_FILES``
below), not a silent pass. If the corpus ever needs a new skip entry,
add it there with a reason string -- do not loosen the plausibility bounds
themselves without an ADR (tests/CLAUDE.md).
"""

from __future__ import annotations

import numpy as np
import pytest

from cins.config import REPO_ROOT, load_config
from cins.cst.io import AirfoilParseError, load_airfoil_dat

CFG = load_config()
UIUC_DIR = REPO_ROOT / "data" / "airfoils" / "uiuc"

# name -> reason. Empty at time of writing: the full 123-file corpus parses
# cleanly (verified by direct enumeration during T8/loader development).
# Any future corpus addition that legitimately can't be parsed goes here
# with its reason, rather than being silently dropped from the panel.
KNOWN_BAD_UIUC_FILES: dict[str, str] = {}

ALL_DAT_FILES = sorted(UIUC_DIR.glob("*.dat"))


def _max_thickness(X: np.ndarray) -> float:
    le_idx = int(np.argmin(X[0]))
    # split at LE (direction-agnostic thickness estimate: interpolate the
    # "other" surface onto one surface's x-grid isn't needed for a coarse
    # plausibility check -- just compare the y-range at each unique x band)
    upper_half = X[:, le_idx:]
    lower_half = X[:, : le_idx + 1]
    # crude common-grid thickness: max over x of (upper y interpolated) -
    # (lower y interpolated) using the denser side's x as the query grid.
    xu, yu = upper_half[0], upper_half[1]
    xl, yl = lower_half[0][::-1], lower_half[1][::-1]
    order_u = np.argsort(xu)
    order_l = np.argsort(xl)
    xu, yu = xu[order_u], yu[order_u]
    xl, yl = xl[order_l], yl[order_l]
    x_common = np.linspace(0.05, 0.95, 50)
    yu_i = np.interp(x_common, xu, yu)
    yl_i = np.interp(x_common, xl, yl)
    return float(np.max(yu_i - yl_i))


def test_uiuc_corpus_file_count_matches_gate():
    assert len(ALL_DAT_FILES) == CFG.gates.io_uiuc_n_files, (
        f"expected {CFG.gates.io_uiuc_n_files} UIUC .dat files, found {len(ALL_DAT_FILES)} "
        "-- if the corpus changed intentionally, update gates.io_uiuc_n_files via an ADR"
    )


def test_uiuc_corpus_all_files_parse_to_plausible_sections():
    x_lo, x_hi = CFG.gates.io_x_range
    failures: list[str] = []
    skipped: list[str] = []

    for path in ALL_DAT_FILES:
        if path.name in KNOWN_BAD_UIUC_FILES:
            skipped.append(path.name)
            continue
        try:
            X = load_airfoil_dat(path)
        except AirfoilParseError as exc:
            failures.append(f"{path.name}: parse error not in skip-list: {exc}")
            continue

        if not np.all(np.isfinite(X)):
            failures.append(f"{path.name}: non-finite coordinates")
            continue
        if X[0].min() < x_lo or X[0].max() > x_hi:
            failures.append(
                f"{path.name}: x/c range [{X[0].min():.4f}, {X[0].max():.4f}] "
                f"outside plausibility band [{x_lo}, {x_hi}]"
            )
            continue
        thickness = _max_thickness(X)
        if not (thickness > CFG.gates.io_min_thickness):
            failures.append(f"{path.name}: max thickness/c={thickness:.3e} <= gate")
            continue

    n_checked = len(ALL_DAT_FILES) - len(skipped)
    assert not failures, (
        f"{len(failures)}/{n_checked} UIUC files failed the plausibility gate:\n"
        + "\n".join(failures)
    )


@pytest.mark.parametrize("reason_name", list(KNOWN_BAD_UIUC_FILES))
def test_known_bad_uiuc_file_actually_fails(reason_name):
    """Guard against a stale skip-list entry: if a file starts parsing
    cleanly again (e.g. after a loader fix), its skip-list entry must be
    removed, not left as dead-weight silently hiding a working file."""
    path = UIUC_DIR / reason_name
    with pytest.raises(AirfoilParseError):
        load_airfoil_dat(path)
