from __future__ import annotations

import pytest


def test_analyze_naca2412_inviscid_alpha2(client):
    """Inviscid solve — fast, used for the default (non-slow) suite. Expected
    cl ~ 0.497 (task spec)."""
    r = client.post("/api/analyze", json={"naca": "2412", "alpha": 2.0})
    assert r.status_code == 200
    data = r.json()
    assert data["converged"] is True
    assert data["cl"] == pytest.approx(0.497, abs=0.02)
    assert len(data["x"]) == len(data["cp"])
    assert len(data["upper"]["x"]) == len(data["upper"]["cp"])
    assert len(data["lower"]["x"]) == len(data["lower"]["cp"])
    assert data["upper"]["x"][0] < data["upper"]["x"][-1]  # ascending, LE->TE
    assert data["lower"]["x"][0] < data["lower"]["x"][-1]


@pytest.mark.slow
def test_analyze_naca2412_viscous_pinned(client):
    """Matches tests/gates/test_t0_baseline.py's pinned NACA 2412 numbers."""
    r = client.post("/api/analyze", json={"naca": "2412", "alpha": 2.0, "Re": 1.0e6})
    assert r.status_code == 200
    data = r.json()
    assert data["converged"] is True
    assert data["cl"] == pytest.approx(0.449351, abs=1e-4)
    assert data["cd"] == pytest.approx(0.005778, abs=5e-5)
    assert data["cm"] == pytest.approx(-0.048030, abs=1e-4)


def test_analyze_naca_code_wrong_length_is_422(client):
    r = client.post("/api/analyze", json={"naca": "999999", "alpha": 2.0})
    assert r.status_code == 422


def test_analyze_non_numeric_naca_is_400(client):
    r = client.post("/api/analyze", json={"naca": "abcd", "alpha": 2.0})
    assert r.status_code == 400


def test_analyze_requires_exactly_one_geometry_source(client):
    r = client.post("/api/analyze", json={"alpha": 2.0})
    assert r.status_code == 422

    r2 = client.post(
        "/api/analyze",
        json={"naca": "2412", "coords": [[0, 0]] * 12, "alpha": 2.0},
    )
    assert r2.status_code == 422


def test_analyze_alpha_out_of_range_is_422(client):
    r = client.post("/api/analyze", json={"naca": "2412", "alpha": 45.0})
    assert r.status_code == 422
