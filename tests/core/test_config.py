"""EvolveConfig resolution — env vars and CLI flag precedence."""

from __future__ import annotations

import pytest
from kairos_evolve.core.config import EvolveConfig, MissingKairosRepoError


def test_config_uses_explicit_path(tmp_path):
    (tmp_path / "skills").mkdir()  # minimal "is-a-kairos-repo" marker
    cfg = EvolveConfig.resolve(kairos_repo=tmp_path)
    assert cfg.kairos_repo == tmp_path
    assert cfg.has_openai_key is False


def test_config_reads_env_var(tmp_path, monkeypatch):
    (tmp_path / "skills").mkdir()
    monkeypatch.setenv("KAIROS_REPO", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = EvolveConfig.resolve()
    assert cfg.kairos_repo == tmp_path


def test_config_explicit_flag_overrides_env(tmp_path, monkeypatch):
    other = tmp_path / "other"
    (tmp_path / "skills").mkdir()
    other.mkdir()
    (other / "skills").mkdir()
    monkeypatch.setenv("KAIROS_REPO", str(tmp_path))
    cfg = EvolveConfig.resolve(kairos_repo=other)
    assert cfg.kairos_repo == other


def test_config_raises_when_kairos_repo_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("KAIROS_REPO", raising=False)
    with pytest.raises(MissingKairosRepoError):
        EvolveConfig.resolve()


def test_config_raises_when_kairos_repo_not_a_kairos_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_REPO", str(tmp_path))  # no skills/ dir
    with pytest.raises(MissingKairosRepoError, match="not a kairos checkout"):
        EvolveConfig.resolve()


def test_config_detects_openai_key(tmp_path, monkeypatch):
    (tmp_path / "skills").mkdir()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    cfg = EvolveConfig.resolve(kairos_repo=tmp_path)
    assert cfg.has_openai_key is True
