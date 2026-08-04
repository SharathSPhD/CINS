"""Thin test alias for building mfoil from raw coordinates.

The vendored ``set_coords`` bug (mfoil.py:1249, ``X.shape(1)`` typo) is worked
around at the adapter level (ADR-0002); tests just use the official facade.
"""

from __future__ import annotations

import numpy as np

from cins.solver.mfoil_adapter import make_mfoil


def mfoil_from_coords(coords: np.ndarray, npanel: int = 199):
    """Construct a headless mfoil instance from a (2, N) coordinate array."""
    return make_mfoil(coords=coords, npanel=npanel)
