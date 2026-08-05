from __future__ import annotations


def test_flowfield_small_grid(client):
    r = client.post(
        "/api/flowfield",
        json={
            "naca": "2412",
            "alpha": 4.0,
            # tight grid straddling mid-chord/mid-thickness so it reliably
            # contains both interior (in-body) and exterior points for a 12%
            # thick section
            "grid": {"nx": 14, "ny": 10, "x_min": 0.2, "x_max": 0.8, "y_min": -0.1, "y_max": 0.1},
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["nx"] == 14
    assert data["ny"] == 10
    assert len(data["speed"]) == 10
    assert len(data["speed"][0]) == 14
    flat_speed = [v for row in data["speed"] for v in row]
    flat_cp = [v for row in data["cp"] for v in row]
    # some points should be outside the body (finite speed/cp)...
    assert any(v is not None for v in flat_speed)
    for v in flat_speed:
        if v is not None:
            assert v >= 0
    # ...and some should be inside the airfoil body (null)
    assert any(v is None for v in flat_speed)
    assert any(v is None for v in flat_cp)


def test_flowfield_grid_too_large_is_422(client):
    r = client.post(
        "/api/flowfield",
        json={"naca": "2412", "alpha": 0.0, "grid": {"nx": 200, "ny": 200}},
    )
    assert r.status_code == 422


def test_flowfield_requires_exactly_one_geometry(client):
    r = client.post("/api/flowfield", json={"alpha": 0.0})
    assert r.status_code == 422
