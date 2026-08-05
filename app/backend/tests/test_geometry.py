from __future__ import annotations

from cins.cst.fit import fit_cst
from cins.solver.mfoil_adapter import make_mfoil


def test_geometry_from_cst_matches_fit(client):
    m = make_mfoil(naca="2412")
    X = m.geom.xpoint
    fitted = fit_cst(X[0], X[1], 8)

    r = client.post(
        "/api/geometry/from-cst",
        json={
            "A_upper": fitted.A_upper.tolist(),
            "A_lower": fitted.A_lower.tolist(),
            "zeta_T_upper": fitted.zeta_T_upper,
            "zeta_T_lower": fitted.zeta_T_lower,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["coords"]) > 10
    d = data["derived"]
    # NACA 2412: max thickness 12%, max camber 2%, near the code's own numbers
    assert 0.10 < d["max_thickness"] < 0.14
    assert 0.0 < d["max_camber"] < 0.04
    assert d["le_radius"] > 0
    assert d["area"] > 0


def test_geometry_from_cst_bad_shape_is_422(client):
    r = client.post("/api/geometry/from-cst", json={"A_upper": [0.1], "A_lower": [0.1, 0.2]})
    assert r.status_code == 422


def test_fit_response_includes_derived(client):
    m = make_mfoil(naca="0012")
    coords = m.geom.xpoint.T.tolist()
    r = client.post("/api/fit", json={"coords": coords, "n": 8})
    assert r.status_code == 200
    d = r.json()["derived"]
    # NACA 0012 is symmetric: camber ~ 0
    assert abs(d["max_camber"]) < 1.0e-3
    assert 0.10 < d["max_thickness"] < 0.14
