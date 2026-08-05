"""Pre-compute the airfoil corpus as one static asset.

The gallery previously fetched geometry per airfoil, which meant 143 requests
against a shared backend and a page that sat on "loading". Everything the
corpus shows is fixed data, so it is generated once here and served as a single
file. Coordinates are decimated to keep the asset small while preserving the
outline, and each entry also carries its fitted CST coefficients so the corpus
can show what the parameterisation makes of each section.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from cins.cst.fit import fit_cst
from cins.cst.io import load_airfoil_dat, uiuc_dat_path
from cins.solver.mfoil_adapter import make_mfoil, naca5_points

NACA = ["0006", "0009", "0010", "0012", "0015", "0018", "0021", "1408", "2408",
        "2412", "2415", "2418", "4412", "4415", "4418", "6409", "6412",
        "23012", "23015", "23018"]
N_FIT = 8
KEEP = 81  # points retained per section


def decimate(X: np.ndarray) -> list[list[float]]:
    idx = np.unique(np.linspace(0, X.shape[1] - 1, KEEP).round().astype(int))
    return [[round(float(X[0, i]), 5), round(float(X[1, i]), 5)] for i in idx]


def summarise(X: np.ndarray) -> dict:
    fit = fit_cst(X[0], X[1], N_FIT)
    i_le = int(np.argmin(X[0]))
    lo_x, lo_y = X[0, : i_le + 1][::-1], X[1, : i_le + 1][::-1]
    up_x, up_y = X[0, i_le:], X[1, i_le:]
    grid = np.linspace(0.0, 1.0, 200)
    up = np.interp(grid, up_x, up_y)
    lo = np.interp(grid, lo_x, lo_y)
    thick, camber = up - lo, 0.5 * (up + lo)
    return {
        "coords": decimate(X),
        "thickness": round(float(thick.max()), 5),
        "thickness_x": round(float(grid[int(thick.argmax())]), 4),
        "camber": round(float(np.abs(camber).max()), 5),
        "camber_x": round(float(grid[int(np.abs(camber).argmax())]), 4),
        "A_upper": [round(float(v), 6) for v in fit.A_upper],
        "A_lower": [round(float(v), 6) for v in fit.A_lower],
        "fit_rms": float(f"{fit.rms:.3e}"),
        "le_radius": round(float(fit.A_upper[0] ** 2 / 2.0), 6),
    }


def main() -> None:
    out: list[dict] = []
    for code in NACA:
        X = naca5_points(code) if len(code) == 5 else np.asarray(
            make_mfoil(naca=code).geom.xpoint, dtype=float)
        out.append({"id": f"naca:{code}", "name": f"NACA {code}", "source": "naca",
                    **summarise(np.asarray(X, dtype=float))})
    for p in sorted(Path("data/airfoils/uiuc").glob("*.dat")):
        try:
            X = load_airfoil_dat(uiuc_dat_path(p.stem))
            out.append({"id": f"uiuc:{p.stem}", "name": p.stem, "source": "uiuc",
                        **summarise(X)})
        except Exception as exc:  # noqa: BLE001 - a corrupt file must not stop the corpus
            print(f"  skipped {p.stem}: {exc}")
    dest = Path("app/frontend/public/corpus.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"n_fit": N_FIT, "airfoils": out}, separators=(",", ":")))
    print(f"wrote {dest}  ({len(out)} sections, {dest.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
