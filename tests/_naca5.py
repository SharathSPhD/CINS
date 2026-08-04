"""Thin test alias for NACA 5-digit coordinates.

The vendored ``naca_points`` 5-digit bug (lists called as functions) is worked
around at the adapter level (ADR-0002); tests just use the official facade.
"""

from __future__ import annotations

from cins.solver.mfoil_adapter import naca5_points  # noqa: F401  (re-export)
