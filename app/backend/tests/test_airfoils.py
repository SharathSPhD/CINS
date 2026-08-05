from __future__ import annotations


def test_list_airfoils_has_uiuc_and_naca(client):
    r = client.get("/api/airfoils")
    assert r.status_code == 200
    data = r.json()
    assert len(data["uiuc"]) > 100  # gates.io_uiuc_n_files == 123
    assert len(data["naca"]) > 0
    entry = data["uiuc"][0]
    assert entry["id"].startswith("uiuc:")
    assert entry["source"] == "uiuc"
    assert entry["thickness"] > 0


def test_airfoil_geometry_uiuc(client):
    r = client.get("/api/airfoils")
    name = r.json()["uiuc"][0]["id"]
    geo = client.get(f"/api/airfoils/{name}/geometry")
    assert geo.status_code == 200
    coords = geo.json()["coords"]
    assert len(coords) > 10
    assert all(len(p) == 2 for p in coords)


def test_airfoil_geometry_naca(client):
    geo = client.get("/api/airfoils/naca:2412/geometry")
    assert geo.status_code == 200
    coords = geo.json()["coords"]
    assert len(coords) > 10


def test_airfoil_geometry_unknown_prefix_is_422(client):
    geo = client.get("/api/airfoils/bogus:2412/geometry")
    assert geo.status_code == 422


def test_airfoil_geometry_missing_uiuc_file_is_422(client):
    geo = client.get("/api/airfoils/uiuc:does-not-exist/geometry")
    assert geo.status_code == 422
