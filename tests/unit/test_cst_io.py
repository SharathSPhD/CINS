"""Unit tests for cins.cst.io (UIUC .dat loader)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cins.cst.fit import fit_cst
from cins.cst.io import AirfoilParseError, detect_format, load_airfoil_dat
from cins.solver.mfoil_adapter import make_mfoil

UIUC_DIR = Path(__file__).resolve().parents[2] / "data" / "airfoils" / "uiuc"
SELIG_EXAMPLE = UIUC_DIR / "ag16.dat"  # single continuous-loop file
LEDNICER_EXAMPLE = UIUC_DIR / "2032c.dat"  # explicit "18. 18." point-count header


def _shoelace_area(X: np.ndarray) -> float:
    return float(np.sum(X[0, :-1] * X[1, 1:] - X[0, 1:] * X[1, :-1]))


def test_detect_format_selig():
    assert detect_format(SELIG_EXAMPLE) == "selig"


def test_detect_format_lednicer():
    assert detect_format(LEDNICER_EXAMPLE) == "lednicer"


def test_load_selig_shape_and_dtype():
    X = load_airfoil_dat(SELIG_EXAMPLE)
    assert X.shape[0] == 2
    assert X.shape[1] >= 4
    assert X.dtype == np.float64


def test_load_lednicer_shape_and_dtype():
    X = load_airfoil_dat(LEDNICER_EXAMPLE)
    assert X.shape[0] == 2
    assert X.shape[1] >= 4
    assert X.dtype == np.float64


def test_load_lednicer_collapses_shared_le_point():
    """Upper/lower blocks each declare the LE point; the stitched loop must
    contain it exactly once (no duplicate consecutive point at the join)."""
    X = load_airfoil_dat(LEDNICER_EXAMPLE)
    le_idx = int(np.argmin(X[0]))
    # no other point should sit within 1e-9 of the LE point in the array
    dists = np.hypot(X[0] - X[0, le_idx], X[1] - X[1, le_idx])
    dists[le_idx] = np.inf
    assert dists.min() > 1e-9


@pytest.mark.parametrize("path", [SELIG_EXAMPLE, LEDNICER_EXAMPLE])
def test_load_chord_normalized_to_unit(path):
    X = load_airfoil_dat(path)
    assert X[0].min() == pytest.approx(0.0, abs=1e-9)
    assert X[0].max() == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("path", [SELIG_EXAMPLE, LEDNICER_EXAMPLE])
def test_load_orientation_matches_mfoil_native_naca(path):
    """mfoil's own CCW convention has NEGATIVE shoelace sum (verified in
    mfoil_adapter._set_coords_fixed against its native naca_points output);
    a loaded section must match that sign, not a textbook CCW convention."""
    X = load_airfoil_dat(path)
    m_ref = make_mfoil(naca="2412", npanel=199)
    assert np.sign(_shoelace_area(X)) == np.sign(_shoelace_area(m_ref.geom.xpoint))
    assert _shoelace_area(X) <= 0.0


@pytest.mark.parametrize("path", [SELIG_EXAMPLE, LEDNICER_EXAMPLE])
def test_load_compatible_with_fit_cst(path):
    X = load_airfoil_dat(path)
    result = fit_cst(X[0], X[1], n=8)
    assert np.isfinite(result.rms)
    assert result.rms < 1e-2  # loose plausibility bound; T2 gate is a separate check


@pytest.mark.parametrize("path", [SELIG_EXAMPLE, LEDNICER_EXAMPLE])
def test_load_compatible_with_make_mfoil_coords(path):
    X = load_airfoil_dat(path)
    m = make_mfoil(coords=X)
    assert m.geom.npoint > 0
    assert np.all(np.isfinite(m.geom.xpoint))


def test_load_missing_file_raises():
    with pytest.raises(AirfoilParseError):
        load_airfoil_dat(UIUC_DIR / "does_not_exist.dat")


def test_load_corrupt_lednicer_count_mismatch(tmp_path):
    bad = tmp_path / "bad.dat"
    bad.write_text("BAD AIRFOIL\n3. 3.\n\n0.0 0.0\n0.5 0.1\n\n0.0 0.0\n0.5 -0.1\n1.0 0.0\n")
    with pytest.raises(AirfoilParseError):
        load_airfoil_dat(bad)


def test_load_corrupt_unparseable_line(tmp_path):
    bad = tmp_path / "bad2.dat"
    bad.write_text("BAD AIRFOIL\nnot a number here\n0.5 0.1\n1.0 0.0\n")
    with pytest.raises(AirfoilParseError):
        load_airfoil_dat(bad)


def test_load_degenerate_zero_chord(tmp_path):
    bad = tmp_path / "flat.dat"
    bad.write_text("FLAT\n0.5 0.0\n0.5 0.0\n0.5 0.1\n0.5 0.0\n")
    with pytest.raises(AirfoilParseError):
        load_airfoil_dat(bad)


# ---------------------------------------------------------------------------
# _ensure_min_te_gap regression (closure-review finding: the fix that
# recovered 63/117 UIUC panel cells had no named test — a refactor could
# silently reopen the failure mode with the suite staying green)
# ---------------------------------------------------------------------------


def test_min_te_gap_opens_sharp_te_and_viscous_solve_survives():
    """Sharp/coincident TE endpoints must be opened to >= MIN_TE_GAP so
    mfoil's build_wake TE-tangent sign test never evaluates on noise
    (vendor mfoil.py:748 assert; killed 63/117 UIUC panel cells 2026-08-05).
    ah21-9 is one of the previously-crashing sections."""
    import numpy as np

    from cins.cst.io import MIN_TE_GAP, load_airfoil_dat

    X = load_airfoil_dat("data/airfoils/uiuc/ah21-9.dat")
    gap = float(np.hypot(*(X[:, -1] - X[:, 0])))
    assert gap >= MIN_TE_GAP - 1e-12

    # duplicated-endpoint synthetic loop: duplicate must drop, gap must open
    psi = np.linspace(0, 1, 40)
    thick = 0.05 * np.sqrt(psi) * (1 - psi)
    xs = np.concatenate([psi[::-1], psi[1:]])
    zs = np.concatenate([-thick[::-1], thick[1:]])
    loop = np.vstack([xs, zs])
    loop = np.hstack([loop, loop[:, :1]])  # exact duplicate closing point
    from cins.cst.io import _ensure_min_te_gap

    Y = _ensure_min_te_gap(loop)
    g2 = float(np.hypot(*(Y[:, -1] - Y[:, 0])))
    assert g2 >= MIN_TE_GAP - 1e-12
    assert Y[1, -1] > Y[1, 0]  # opened along thickness: upper above lower


def test_min_te_gap_leaves_open_te_untouched():
    import numpy as np

    from cins.cst.io import load_airfoil_dat

    X = load_airfoil_dat("data/airfoils/uiuc/davis.dat")  # large flat-back TE
    gap = float(np.hypot(*(X[:, -1] - X[:, 0])))
    assert gap > 0.01  # untouched, well above the minimum
