"""Facade over vendored mfoil — the ONLY module allowed to touch vendor/mfoil.

Provides:
- import shim for the vendored single-file module,
- a scipy>=1.11 compatibility shim (see ADR-0001) applied without editing vendor code,
- construction helpers that return a solver configured for headless (no-plot) use.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import matplotlib
import numpy as np

matplotlib.use("Agg")  # vendored mfoil imports pyplot; never open windows

VENDOR_DIR = Path(__file__).resolve().parents[3] / "vendor" / "mfoil"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

import mfoil as _mfoil_mod  # noqa: E402  (vendored module)

if TYPE_CHECKING:
    pass


class _AlwaysReallocGlob(_mfoil_mod.Glob):
    """scipy>=1.11 compatibility (ADR-0001).

    mfoil v2023-06-28 line 2059 compares a sparse matrix to a shape tuple
    (missing `.shape`), which modern scipy raises on. Forcing `realloc` True
    short-circuits that comparison; cost is one sparse re-allocation per
    Newton iteration, which mfoil itself pays on iteration 1 anyway.
    """

    @property
    def realloc(self) -> bool:  # type: ignore[override]
        return True

    @realloc.setter
    def realloc(self, value: Any) -> None:  # vendor assigns True/False; ignore
        pass


def make_mfoil(naca: str | None = "2412", coords=None, npanel: int | None = None):
    """Construct a headless mfoil instance with the compatibility shims applied.

    ``npanel=None`` (default) resolves from ``configs/default.yaml``
    (``paneling.npanel``) so the adapter cannot drift from the declared single
    source of truth; pass an explicit value only for deliberate overrides.

    Routes around two vendor bugs (ADR-0002): ``set_coords`` is broken as shipped
    (``X.shape(1)`` typo), so ``coords=`` input is paneled here instead; the
    5-digit branch of ``naca_points`` is broken (lists called as functions), so
    5-digit codes are generated here and routed through the coords path.
    """
    if npanel is None:
        from cins.config import load_config

        npanel = load_config().paneling.npanel

    if coords is None and naca is not None and len(str(naca)) == 5:
        coords = naca5_points(str(naca))
        name = f"NACA {naca}"
        naca = None
    else:
        name = None

    if coords is not None:
        m = _mfoil_mod.mfoil(naca="0012", npanel=npanel)  # geometry discarded below
        _set_coords_fixed(m, np.asarray(coords, dtype=float), npanel)
        if name:
            m.geom.name = name
    else:
        m = _mfoil_mod.mfoil(naca=naca, npanel=npanel)
    _apply_shims(m)
    m.param.doplot = False
    m.param.verb = 0
    return m


def _set_coords_fixed(m, X: "np.ndarray", npanel: int) -> None:
    """What vendor set_coords (mfoil.py:1249) does, with its typo fixed (ADR-0002).

    Accepts (2, N) or (N, 2); ensures CCW ordering by the vendor's own signed-area
    convention; re-panels via the vendor's make_panels.
    """
    if X.shape[0] != 2:
        X = X.T
    # Orientation: mfoil's convention (TE-lower -> LE -> TE-upper) has NEGATIVE
    # shoelace sum (verified against vendor naca_points output); reverse if positive.
    area = np.sum(X[0, :-1] * X[1, 1:] - X[0, 1:] * X[1, :-1])
    if area > 0:
        X = X[:, ::-1]
    m.geom.npoint = X.shape[1]
    m.geom.xpoint = X
    m.geom.chord = float(X[0, :].max() - X[0, :].min())
    _mfoil_mod.make_panels(m, npanel, None)


def naca5_points(digits: str, npoint_per_side: int = 100):
    """NACA 5-digit coordinates, (2, N) CCW — vendor naca_points 5-digit branch
    with its list-call bug fixed (mv[int(n)-1], not mv(n)). ADR-0002."""
    assert len(digits) == 5, "NACA 5-digit code required, e.g. '23012'"
    N, te = npoint_per_side, 1.5
    f = np.linspace(0.0, 1.0, N + 1)
    x = 1 - (te + 1) * f * (1 - f) ** te - (1 - f) ** (te + 1)

    t_dist = 0.2969 * np.sqrt(x) - 0.126 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1015 * x**4
    tmax = float(digits[-2:]) * 0.01
    t = t_dist * tmax / 0.2

    n = float(digits[1])
    valid = digits[0] == "2" and digits[2] == "0" and 0 < n < 6
    assert valid, "5-digit NACA must begin with 2X0, X in 1-5"
    mv = [0.058, 0.126, 0.2025, 0.29, 0.391]
    cv = [361.4, 51.64, 15.957, 6.643, 3.23]
    idx = int(round(n)) - 1
    m_c, cc = mv[idx], cv[idx]

    c = (cc / 6.0) * (x**3 - 3 * m_c * x**2 + m_c**2 * (3 - m_c) * x)
    aft = x > m_c
    c[aft] = (cc / 6.0) * m_c**3 * (1 - x[aft])

    zu = c + t
    zl = c - t
    xs = np.concatenate((np.flip(x), x[1:]))
    zs = np.concatenate((np.flip(zl), zu[1:]))
    return np.vstack([xs, zs])


def _apply_shims(m) -> None:
    """Swap m.glob's class so `realloc` always reads True (vendor file untouched)."""
    if not isinstance(m.glob, _AlwaysReallocGlob):
        m.glob.__class__ = _AlwaysReallocGlob


def mfoil_module():
    """Access to the vendored module's free functions (for introspection/pre-solve)."""
    return _mfoil_mod
