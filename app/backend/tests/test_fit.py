from __future__ import annotations

from cins.solver.mfoil_adapter import make_mfoil


def test_fit_round_trip(client):
    m = make_mfoil(naca="2412")
    X = m.geom.xpoint  # (2, N)
    coords = X.T.tolist()

    r = client.post("/api/fit", json={"coords": coords, "n": 8})
    assert r.status_code == 200
    data = r.json()
    assert data["rms"] < 1.0e-3  # gates.t2_fit_rms_max
    assert len(data["A_upper"]) == 9  # n+1
    assert len(data["A_lower"]) == 9
    assert data["gram_condition"] > 0
    assert data["n"] == 8


def test_fit_too_few_points_is_422(client):
    r = client.post("/api/fit", json={"coords": [[0, 0], [1, 0]], "n": 8})
    assert r.status_code == 422


def test_fit_bad_coords_shape_is_422(client):
    r = client.post("/api/fit", json={"coords": [[0, 0, 0]] * 12, "n": 8})
    assert r.status_code == 422
