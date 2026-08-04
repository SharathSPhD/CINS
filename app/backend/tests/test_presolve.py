from __future__ import annotations

import pytest


def test_presolve_self_target_is_realisable(client):
    """Targeting the airfoil's own inviscid Cp against its own CST fit as the
    baseline should be (near-)exactly realisable (ADR-0004 metric 1)."""
    analyzed = client.post("/api/analyze", json={"naca": "2412", "alpha": 2.0}).json()

    r = client.post(
        "/api/presolve",
        json={
            "baseline": {"naca": "2412"},
            "target": {"x": analyzed["x"], "cp": analyzed["cp"], "kind": "inviscid"},
            "n": 8,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["realisable"] is True
    assert data["realisability"] < 0.05
    assert data["realisability_label"] == "inviscid-consistent (ADR-0004)"
    assert data["model_gap"] is None
    assert len(data["A_upper_init"]) == 9
    assert len(data["A_lower_init"]) == 9


def test_presolve_with_shared_le_radius_constraint(client):
    analyzed = client.post("/api/analyze", json={"naca": "2412", "alpha": 2.0}).json()

    r = client.post(
        "/api/presolve",
        json={
            "baseline": {"naca": "2412"},
            "target": {"x": analyzed["x"], "cp": analyzed["cp"], "kind": "inviscid"},
            "constraints": [{"type": "shared_le_radius"}],
            "n": 8,
        },
    )
    assert r.status_code == 200
    data = r.json()
    # constraint row is A_u0 + A_l0 = 0
    assert data["A_upper_init"][0] == pytest.approx(-data["A_lower_init"][0], abs=1e-8)


def test_presolve_unknown_baseline_is_422(client):
    r = client.post(
        "/api/presolve",
        json={
            "baseline": {},
            "target": {"x": [0.0, 0.5, 1.0, 0.2, 0.8], "cp": [0.0, -0.5, 0.1, -0.2, 0.0]},
        },
    )
    assert r.status_code == 422


def test_presolve_area_constraint_requires_target_area(client):
    analyzed = client.post("/api/analyze", json={"naca": "2412", "alpha": 2.0}).json()
    r = client.post(
        "/api/presolve",
        json={
            "baseline": {"naca": "2412"},
            "target": {"x": analyzed["x"], "cp": analyzed["cp"]},
            "constraints": [{"type": "area"}],
        },
    )
    assert r.status_code == 422
