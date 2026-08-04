"""Facade over vendored mfoil — the ONLY module allowed to touch vendor/mfoil.

Provides:
- import shim for the vendored single-file module,
- a scipy>=1.11 compatibility shim (see ADR-0001) applied without editing vendor code,
- construction helpers that return a solver configured for headless (no-plot) use.
"""

from __future__ import annotations

import copy
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


# --- forced transition (ADR-0003) -------------------------------------------
#
# Two independent vendor entry points determine transition and BOTH must be
# neutralized for a forced trip to be self-consistent:
#
#  1. `update_transition` (mfoil.py:2507) re-derives `M.vsol.turb` every outer
#     Newton iteration by marching the amplification-factor ODE
#     (`march_amplification`) and re-flagging turb where it crosses
#     `param.ncrit`. Left alone, it would immediately un-force the trip.
#     -> replaced with a no-op while forcing is active (unchanged from the
#        original shim).
#  2. `residual_transition` (mfoil.py:2623), called by `build_glob_sys`
#     wherever `M.vsol.turb[i-1] ^ M.vsol.turb[i]` is true (mfoil.py:2125),
#     is itself a natural-transition closure: it solves an internal
#     sub-Newton for a station-local point xt where the marched
#     amplification equals `param.ncrit`, and blends a laminar [x1,xt] leg
#     with a turbulent [xt,x2] leg. That equation is only valid when
#     transition is in fact governed by amplification reaching ncrit at some
#     xt inside the station -- which is false once transition is forced away
#     from its natural location (e.g. amplification is still ~2, not
#     ncrit~9, at a forced 5%c trip). Leaving `residual_transition`
#     unreplaced leaves this inconsistent equation IN the residual at the
#     forced trip's boundary station: the trip's node-index turb pattern and
#     the frozen glob.U vector move correctly under Newton pressure from
#     every *other* row, but the boundary station's own natural-transition
#     row can never be satisfied by a forced state, so Rnorm stalls and
#     glob.conv never goes True.
#     -> replaced with `_residual_transition_forced` (below) while forcing is
#        active.
#
# Both are free module-level functions in vendor mfoil.py (called as bare
# names, not `M.` methods), so both are shimmed by module-level reassignment,
# exactly the ADR-0001 pattern.

_original_update_transition = _mfoil_mod.update_transition
_original_residual_transition = _mfoil_mod.residual_transition


def _residual_transition_forced(M, param, x, U, Aux):
    """Forced-trip onset-station residual (ADR-0003).

    Installed in place of vendor's ``residual_transition`` for the duration
    of a forced-transition solve. ``build_glob_sys`` calls this at exactly
    the station where the (forced) ``M.vsol.turb`` pattern flips
    (``tran = turb[i-1] ^ turb[i]``, mfoil.py:2125) -- i.e. the boundary
    station straddling the pinned trip location.

    Modeling choice (XFOIL-trip style, documented in ADR-0003): rather than
    solving for an internal transition point xt (vendor's natural-transition
    closure, meaningless here since amplification at a forced trip need not
    equal ``ncrit``), the entire boundary station ``[x1, x2]`` is treated as
    the onset of turbulence:

    - Momentum (row 0) and shape-parameter (row 1): the vendor's own
      ``residual_station`` evaluated directly on ``[x1, x2]`` with
      ``param.turb=True`` -- the pure-turbulent closure applied across the
      boundary station, with no laminar sub-leg. This is the standard
      XFOIL-like approximation for a station forced into turbulence, and it
      is what the *next* (fully turbulent) station in ``build_glob_sys``
      already uses, so the closure is continuous going downstream.
    - Shear-lag row (row 2, ``Rlag`` inside ``residual_station``): REPLACED.
      In turbulent mode ``residual_station`` row 2 is a shear-lag ODE
      relating ``sa[0]=U1[2]`` to ``sa[1]=U2[2]``; at an onset station
      ``U1[2]`` is the *upstream laminar* node's amplification factor, not a
      shear-stress coefficient, so that ODE is not meaningful here. Instead
      this row imposes the same turbulence-onset closure mfoil's own
      ``update_transition``/``set_forced_transition`` use to initialize a
      newly-turbulent node: ``U2[2] (ctau) == cttr(U2)`` (``get_cttr``,
      mfoil.py:3004, the transition-correlation root-shear-stress value).
      This closure depends only on the downstream state ``U2`` -- ``cttr``
      is a function of th/Hk/Ret/ue at U2 only, not of ``sa`` -- so
      ``R_U[2, 0:4] = 0`` (no U1 dependence) and ``R_x[2, :] = 0`` (no x
      dependence).

    No station-local xt is needed or computed: because the momentum/shape
    rows use the station's real endpoints ``[x1, x2]`` directly (no
    laminar/turbulent blend), nothing here depends on where *within*
    ``[x1, x2]`` the natural trip would have occurred. The trip location is
    pinned entirely by ``set_forced_transition``'s node-index ``turb``
    pattern, not by any quantity computed inside this function.

    Parameters/returns match vendor ``residual_transition`` exactly (R: 3x1,
    R_U: 3x8 as [R_U1, R_U2], R_x: 3x2 as [R_x1, R_x2]) so it drops into
    ``build_glob_sys`` unmodified.
    """
    param_turb = copy.deepcopy(param)
    param_turb.turb = True
    residual_station = _mfoil_mod.residual_station
    get_cttr = _mfoil_mod.get_cttr

    U2 = U[:, 1]
    # residual_station's turbulent row 2 (Rlag, discarded below) evaluates
    # log(sa[1]/sa[0]) where sa[0]=U1[2] is the upstream LAMINAR node's
    # amplification factor -- not a valid shear-stress coefficient, so this
    # can be zero/negative and produce a benign (discarded) nan/inf. Silence
    # the resulting RuntimeWarning rather than let it leak to callers.
    with np.errstate(divide="ignore", invalid="ignore"):
        R, R_U, R_x = residual_station(param_turb, x, U, Aux)
        cttr, cttr_U = get_cttr(U2, param_turb)

    R = R.copy()
    R_U = R_U.copy()
    R_x = R_x.copy()
    R[2] = U2[2] - cttr
    R_U[2, 0:4] = 0.0
    R_U[2, 4:8] = np.array([0.0, 0.0, 1.0, 0.0]) - cttr_U
    R_x[2, :] = 0.0

    return R, R_U, R_x


def set_forced_transition(m, xtr_upper: float, xtr_lower: float) -> None:
    """Freeze the transition pattern at fixed trip locations (ADR-0003, FM-4).

    Overwrites ``m.vsol.turb`` per surface by x/c threshold and suppresses
    BOTH of mfoil's transition-consistency paths (module-level no-ops/
    replacements, same shim pattern as ADR-0001): ``update_transition``
    (would re-derive the turb pattern every Newton iteration) and
    ``residual_transition`` (the natural-transition station equation, which
    is inconsistent with a forced trip -- see ``_residual_transition_forced``
    docstring). Requires a solved/initialized viscous state
    (``m.vsol.Is`` populated). Call ``release_transition()`` before a
    natural-transition verification solve.
    """
    assert len(m.vsol.Is) == 3, "viscous surfaces not identified; solve/init first"
    chord = m.geom.chord
    x = m.foil.x[0]
    for si, xtr in ((0, xtr_lower), (1, xtr_upper)):
        # mfoil surface 0 = lower, 1 = upper (Is walks stag -> TE); wake (2) always turb
        Is = np.fromiter(m.vsol.Is[si], dtype=int)
        want_turb = (x[Is] / chord >= xtr).astype(int)
        cur_turb = np.asarray(m.vsol.turb[Is])
        if np.any((cur_turb == 1) & (want_turb == 0)):
            raise ValueError(
                f"forced trip x/c={xtr} on surface {si} is AFT of the current "
                "transition; laminarizing turbulent nodes is not supported (ADR-0003)"
            )
        newly = np.nonzero((want_turb == 1) & (cur_turb == 0))[0]
        if newly.size:
            # mimic update_transition's earlier-transition branch (mfoil.py): give
            # each flipped node a proper initial ctau via get_cttr, ramping toward
            # the first already-turbulent node's value if one exists
            param = _mfoil_mod.build_param(m, si)
            param.turb = True
            sa0, _ = _mfoil_mod.get_cttr(m.glob.U[:, Is[newly[0]]], param)
            first_old_turb = np.nonzero(cur_turb == 1)[0]
            sa1 = m.glob.U[2, Is[first_old_turb[0]]] if first_old_turb.size else sa0
            xi = m.isol.xi[Is]
            span = xi[newly[-1]] - xi[newly[0]]
            for k, j in enumerate(newly):
                f = 0.0 if span == 0 else (xi[j] - xi[newly[0]]) / span
                m.glob.U[2, Is[j]] = sa0 + f * (sa1 - sa0)
                m.vsol.turb[Is[j]] = 1
    m.vsol.turb[np.fromiter(m.vsol.Is[2], dtype=int)] = 1  # wake always turbulent
    _mfoil_mod.update_transition = lambda M: None
    _mfoil_mod.residual_transition = _residual_transition_forced


def release_transition() -> None:
    """Restore mfoil's natural e^n transition (ADR-0003)."""
    _mfoil_mod.update_transition = _original_update_transition
    _mfoil_mod.residual_transition = _original_residual_transition


class forced_transition:
    """Context manager wrapping set_forced_transition/release_transition."""

    def __init__(self, m, xtr_upper: float, xtr_lower: float):
        self.args = (m, xtr_upper, xtr_lower)

    def __enter__(self):
        set_forced_transition(*self.args)
        return self.args[0]

    def __exit__(self, *exc):
        release_transition()
        return False
