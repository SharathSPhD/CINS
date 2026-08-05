from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engine import UIUC_DIR  # noqa: E402 - path extended above


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


def test_upload_dat_file_returns_geometry_and_fit(client):
    """Item 6 of the app rich-features brief — POST a real UIUC .dat file
    (any one from the corpus, reused here purely as a valid sample file, not
    testing the corpus loader itself) through the multipart upload endpoint
    and confirm it comes back parsed + CST-fitted."""
    sample = sorted(UIUC_DIR.glob("*.dat"))[0]
    with open(sample, "rb") as f:
        r = client.post(
            "/api/airfoils/upload",
            files={"file": (sample.name, f, "text/plain")},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == f"upload:{sample.stem}"
    assert data["n_points"] == len(data["coords"])
    assert data["n_points"] > 10
    assert len(data["fit"]["A_upper"]) > 0
    assert data["fit"]["derived"]["le_radius"] > 0


def test_upload_garbage_file_is_422(client):
    r = client.post(
        "/api/airfoils/upload",
        files={"file": ("junk.dat", b"not an airfoil\nfile at all\n", "text/plain")},
    )
    assert r.status_code == 422
