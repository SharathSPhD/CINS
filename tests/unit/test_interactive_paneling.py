"""Interactive paneling: the accuracy price of the application's faster solve.

The application runs on a shared free-tier container roughly 33x slower than a
development machine, where a 199-panel viscous solve measures about 115 s. The
study paneling is not negotiable for the manuscript, so the application gets
its own count and this test pins what that costs.

The tolerances here are the claim made in ``configs/default.yaml`` and in the
application README. They are deliberately tight: if a future paneling change
degrades the interactive solve beyond this, the claim is wrong and this test
should fail rather than the documentation quietly becoming false.
"""

from __future__ import annotations

import numpy as np
import pytest

from cins.config import load_config
from cins.solver.mfoil_adapter import make_mfoil

ALPHA = 2.0
RE = 1.0e6


def _solve(npanel: int):
    m = make_mfoil(naca="2412", npanel=npanel)
    m.setoper(alpha=ALPHA, Re=RE)
    m.solve()
    assert m.glob.conv, f"viscous solve did not converge at npanel={npanel}"
    return m


def _surface(x, v, le_idx, upper: bool):
    sl = slice(le_idx, None) if upper else slice(None, le_idx + 1)
    a, b = np.asarray(x)[sl], np.asarray(v)[sl]
    order = np.argsort(a)
    return a[order], b[order]


@pytest.fixture(scope="module")
def pair():
    cfg = load_config()
    return _solve(cfg.paneling.npanel), _solve(cfg.paneling.npanel_interactive)


def test_interactive_paneling_is_coarser_than_the_study_paneling():
    cfg = load_config()
    assert cfg.paneling.npanel_interactive < cfg.paneling.npanel


def test_interactive_lift_matches_study_paneling(pair):
    ref, app = pair
    assert abs(float(app.post.cl) - float(ref.post.cl)) < 2.0e-3


def test_interactive_drag_matches_study_paneling_within_one_percent(pair):
    ref, app = pair
    rel = abs(float(app.post.cd) - float(ref.post.cd)) / float(ref.post.cd)
    assert rel < 0.01, f"cd differs by {rel * 100:.2f}%"


def test_interactive_pressure_distribution_tracks_study_paneling(pair):
    """Compared per surface on a common chordwise grid. Comparing the raw node
    arrays instead would fold the leading-edge wrap into the error, which is a
    paneling artefact rather than a difference in the solution."""
    ref, app = pair
    grid = np.linspace(0.02, 0.98, 200)
    resid = []
    for m in (ref, app):
        x = np.asarray(m.foil.x[0], dtype=float)
        cp = np.asarray(m.post.cp, dtype=float)[: m.foil.N]
        le = int(np.argmin(x))
        resid.append([np.interp(grid, *_surface(x, cp, le, up)) for up in (True, False)])
    diff = np.concatenate([a - b for a, b in zip(resid[0], resid[1], strict=True)])
    assert float(np.sqrt(np.mean(diff**2))) < 3.0e-3
