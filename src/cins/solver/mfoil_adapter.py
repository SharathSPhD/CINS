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


def make_mfoil(naca: str | None = "2412", coords=None, npanel: int = 199):
    """Construct a headless mfoil instance with the compatibility shim applied."""
    if coords is not None:
        m = _mfoil_mod.mfoil(coords=coords, npanel=npanel)
    else:
        m = _mfoil_mod.mfoil(naca=naca, npanel=npanel)
    _apply_shims(m)
    m.param.doplot = False
    m.param.verb = 0
    return m


def _apply_shims(m) -> None:
    """Swap m.glob's class so `realloc` always reads True (vendor file untouched)."""
    if not isinstance(m.glob, _AlwaysReallocGlob):
        m.glob.__class__ = _AlwaysReallocGlob


def mfoil_module():
    """Access to the vendored module's free functions (for introspection/pre-solve)."""
    return _mfoil_mod
