"""Config schema: load, validate, hash stability, overlay merge."""

import pytest

from cins.config import CinsConfig, load_config


def test_default_config_loads_and_validates():
    cfg = load_config()
    assert isinstance(cfg, CinsConfig)
    assert cfg.cst.N1 == 0.5
    assert cfg.gates.t7_max_newton_iters <= 9


def test_config_hash_stable():
    assert load_config().config_hash() == load_config().config_hash()


def test_invalid_le_treatment_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("cst:\n  le_treatment: banana\n")
    with pytest.raises(Exception):
        load_config(p)


def test_overlay_deep_merges(tmp_path):
    p = tmp_path / "overlay.yaml"
    p.write_text("cst:\n  n_upper: 12\n")
    cfg = load_config(p)
    assert cfg.cst.n_upper == 12
    assert cfg.cst.n_lower == 8  # untouched default
    assert cfg.config_hash() != load_config().config_hash()


def test_t8_airfoil_uiuc_prefix_accepted_when_file_exists(tmp_path):
    p = tmp_path / "overlay.yaml"
    p.write_text('t8:\n  airfoil: "uiuc:ag16"\n')
    cfg = load_config(p)
    assert cfg.t8.airfoil == "uiuc:ag16"


def test_t8_airfoil_uiuc_prefix_rejected_when_file_missing(tmp_path):
    p = tmp_path / "overlay.yaml"
    p.write_text('t8:\n  airfoil: "uiuc:does_not_exist"\n')
    with pytest.raises(Exception):
        load_config(p)
