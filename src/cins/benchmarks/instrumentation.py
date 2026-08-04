"""H2 evaluation-currency instrumentation (STATS_PROTOCOL §1, dossier §7.9 last
ablation row).

H2's headline claim is a *count of flow-residual evaluations*, not wall time.
This module counts, non-invasively, the two currencies the paper needs:

- ``n_residual_evaluations``: every call to
  ``cins.solver.geometry_update.flow_residual`` — both the one-per-Newton-
  iteration residual assembly and every column of ``dR_dA_fd``'s central
  difference (dossier §7.6: "~20 columns ... 20 residual *evaluations* (not
  solves) per Newton step"). ``dR_dA_fd`` calls ``flow_residual`` as a bare
  name resolved from its own module's globals, so patching the module
  attribute counts both call sites without touching solver code.
- ``n_flow_solves_equivalent``: every *converged nonlinear flow solve*
  (vendor ``solve_coupled`` — the viscous Newton solve — and
  ``solve_inviscid`` — the cheap linear inviscid solve used for warm starts
  and T4's sensitivity finite differences). This is the currency the nested
  ``scipy.least_squares`` control baseline (``control.py``) also reports,
  making the ratio ``evals_nested / evals_monolithic`` (H2) an apples-to-
  apples comparison. ``mfoil.solve()`` itself is deliberately NOT patched —
  it only dispatches to ``solve_inviscid``/``solve_coupled``, so patching it
  too would double-count.

Implemented as monkeypatches restored on exit (same module-level-reassignment
shim pattern as ADR-0001/ADR-0003), since the counted functions are called
from inside ``cins.solver.newton``/``geometry_update``/``presolve``, which
this benchmarking package must not modify (T8 is infrastructure, not a T5/T4
change).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cins.solver.geometry_update as _geom_mod
import cins.solver.mfoil_adapter as _adapter_mod
import cins.solver.newton as _newton_mod

__all__ = ["EvalCounters", "instrument_evaluations"]


@dataclass
class EvalCounters:
    """H2 currency counters for one pipeline run (dossier §7.9 last row)."""

    n_residual_evaluations: int = 0
    n_flow_solves_equivalent: int = 0
    _breakdown: dict[str, int] = field(default_factory=dict, repr=False)

    def _bump(self, key: str, n: int = 1) -> None:
        self._breakdown[key] = self._breakdown.get(key, 0) + n

    def as_dict(self) -> dict[str, int]:
        return {
            "n_residual_evaluations": self.n_residual_evaluations,
            "n_flow_solves_equivalent": self.n_flow_solves_equivalent,
            "breakdown": dict(self._breakdown),
        }


class instrument_evaluations:
    """Context manager: tally ``counters`` while the block runs.

    Usage::

        counters = EvalCounters()
        with instrument_evaluations(counters):
            ... run the T7-style pipeline ...
    """

    def __init__(self, counters: EvalCounters):
        self.counters = counters
        self._orig: dict[str, object] = {}

    def __enter__(self) -> EvalCounters:
        vendor = _adapter_mod.mfoil_module()
        counters = self.counters

        orig_flow_residual = _geom_mod.flow_residual
        orig_solve_coupled = vendor.solve_coupled
        orig_solve_inviscid = vendor.solve_inviscid

        def counted_flow_residual(m):
            counters.n_residual_evaluations += 1
            counters._bump("flow_residual")
            return orig_flow_residual(m)

        def counted_solve_coupled(m):
            counters.n_flow_solves_equivalent += 1
            counters._bump("solve_coupled")
            return orig_solve_coupled(m)

        def counted_solve_inviscid(m):
            counters.n_flow_solves_equivalent += 1
            counters._bump("solve_inviscid")
            return orig_solve_inviscid(m)

        self._orig = {
            "geom.flow_residual": orig_flow_residual,
            "newton.flow_residual": _newton_mod.flow_residual,
            "vendor.solve_coupled": orig_solve_coupled,
            "vendor.solve_inviscid": orig_solve_inviscid,
        }

        # Patch the module attribute (covers dR_dA_fd's internal bare-name
        # lookup) AND newton's already-imported reference (from-import copies
        # a name binding, so the module attribute patch alone would not reach
        # calls made from inside solve_inverse).
        _geom_mod.flow_residual = counted_flow_residual
        _newton_mod.flow_residual = counted_flow_residual
        vendor.solve_coupled = counted_solve_coupled
        vendor.solve_inviscid = counted_solve_inviscid
        return counters

    def __exit__(self, *exc) -> bool:
        vendor = _adapter_mod.mfoil_module()
        _geom_mod.flow_residual = self._orig["geom.flow_residual"]
        _newton_mod.flow_residual = self._orig["newton.flow_residual"]
        vendor.solve_coupled = self._orig["vendor.solve_coupled"]
        vendor.solve_inviscid = self._orig["vendor.solve_inviscid"]
        return False
