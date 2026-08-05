from __future__ import annotations


def test_showcase_returns_t7_panel_and_figures(client):
    """Item 7 of the app rich-features brief: /api/showcase reads the
    archived T7 self-consistency run + T8 NACA panel sweep + paper figures
    from experiments/results/, read-only, for the Results Gallery page."""
    r = client.get("/api/showcase")
    assert r.status_code == 200
    data = r.json()

    assert data["t7"]["convergence_order"] is not None
    assert len(data["t7"]["residual_history"]) > 0
    assert "T7 GATE" in data["t7"]["log_tail"] or len(data["t7"]["log_tail"]) > 0

    assert data["panel_n_total"] > 0
    assert data["panel_n_converged"] <= data["panel_n_total"]
    assert len(data["panel"]) == data["panel_n_total"]
    assert all("cell_name" in p for p in data["panel"])

    assert isinstance(data["figures"], list)
    assert all(f.startswith("/static/figures/") for f in data["figures"])

    assert data["gates"] is not None
    assert data["gates"]["project"].startswith("CINS")
