"""Regression tests for the demo animation's surface-error computation.

The first implementation interpolated a closed airfoil loop against itself with
``np.interp``. Because x is not monotonic around a loop, that returns the
thickness distribution rather than the error, which made a converged solve look
as though it carried an 80 millichord surface error. These tests pin the
per-surface behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "experiments"))

make_demo_frames = pytest.importorskip("make_demo_frames")
split_surfaces = make_demo_frames.split_surfaces
surface_error = make_demo_frames.surface_error


def _loop(scale: float = 1.0, n: int = 60):
    """A symmetric closed loop in the project's TE-lower to TE-upper order."""
    psi = np.linspace(0.0, 1.0, n)
    thick = 0.06 * np.sqrt(psi) * (1.0 - psi) * scale
    x = np.concatenate([psi[::-1], psi[1:]])
    y = np.concatenate([-thick[::-1], thick[1:]])
    return x, y


def test_split_surfaces_returns_monotonic_branches():
    x, y = _loop()
    (lo_x, lo_y), (up_x, up_y) = split_surfaces(x, y)
    assert np.all(np.diff(lo_x) >= 0)
    assert np.all(np.diff(up_x) >= 0)
    assert np.all(lo_y <= 1e-15)
    assert np.all(up_y >= -1e-15)


def test_identical_geometry_has_zero_surface_error():
    x, y = _loop()
    assert np.max(np.abs(surface_error(x, y, x, y))) == 0.0


def test_thickened_geometry_reports_the_thickness_difference():
    """A 1.5x thicker section must report half the reference thickness as the
    peak error, not the full thickness distribution."""
    x, y = _loop()
    _, y_thick = _loop(scale=1.5)
    err = surface_error(x, y_thick, x, y)
    expected = 0.5 * float(np.max(np.abs(y)))
    assert np.max(np.abs(err)) == pytest.approx(expected, rel=1e-9)


def test_error_is_signed_per_surface():
    x, y = _loop()
    _, y_thick = _loop(scale=1.5)
    err = surface_error(x, y_thick, x, y)
    i_le = int(np.argmin(x))
    assert err[:i_le].min() < 0  # lower surface moves down
    assert err[i_le:].max() > 0  # upper surface moves up


def test_error_is_insensitive_to_node_count_of_the_target():
    """The target is sampled on the CST psi grid and the current geometry on the
    solver's panel nodes, so the two arrays differ in length."""
    x, y = _loop(n=60)
    tx, ty = _loop(n=140)
    assert np.max(np.abs(surface_error(x, y, tx, ty))) < 5e-4
