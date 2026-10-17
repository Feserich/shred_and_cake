import sys
from pathlib import Path

from skibasar import config


def test_data_dir_defaults_to_working_directory(monkeypatch):
    monkeypatch.delenv("SKIBASAR_DATA_DIR", raising=False)
    assert config.data_dir() == Path("data")


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SKIBASAR_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path


def test_data_dir_next_to_frozen_executable(monkeypatch, tmp_path):
    monkeypatch.delenv("SKIBASAR_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "skibasar"))
    assert config.data_dir() == tmp_path.resolve() / "data"
