from pathlib import Path

import pytest

from metapet import paths


def test_explicit_flag_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("METAPET_HOME", str(tmp_path / "env"))
    home = paths.resolve(tmp_path / "flag")
    assert home.path == tmp_path / "flag"
    assert home.source == "--home flag"


def test_env_beats_portable_and_default(monkeypatch, tmp_path):
    portable = tmp_path / "data"
    portable.mkdir()
    monkeypatch.setattr(paths, "portable_dir", lambda: portable)
    monkeypatch.setenv("METAPET_HOME", str(tmp_path / "env"))
    assert paths.resolve().path == tmp_path / "env"


def test_portable_used_only_when_it_exists(monkeypatch, tmp_path):
    portable = tmp_path / "data"
    monkeypatch.setattr(paths, "portable_dir", lambda: portable)
    assert paths.resolve().source == "platform default"
    portable.mkdir()
    home = paths.resolve()
    assert home.path == portable
    assert home.source.startswith("portable")


def test_platform_default(monkeypatch):
    monkeypatch.setattr(paths, "portable_dir", lambda: None)
    home = paths.resolve()
    assert home.source == "platform default"
    assert "metapet" in home.path.parts[-1]


@pytest.mark.skipif(
    paths.checkout_root() is None, reason="metapet is installed, not run from a source checkout"
)
def test_checkout_root_detected_from_source_tree():
    root = paths.checkout_root()
    assert root is not None and (root / "pyproject.toml").is_file()
    assert paths.portable_dir() == Path(root) / "data"
