"""Runner Protocol + FakeRunner + KairosSubprocessRunner."""

from __future__ import annotations

from pathlib import Path

from kairos_evolve.core.runner import (
    FakeRunner,
    KairosSubprocessRunner,
    Runner,
    RunResult,
)


def test_fake_runner_returns_canned():
    runner = FakeRunner(output_text="canned response", succeeded=True)
    result = runner.run(skill_dir=Path("/dev/null"), inputs={"q": "hi"})
    assert result.succeeded is True
    assert result.output_text == "canned response"
    assert result.error is None


def test_fake_runner_records_calls():
    runner = FakeRunner(output_text="x")
    runner.run(skill_dir=Path("/a"), inputs={"q": "1"})
    runner.run(skill_dir=Path("/b"), inputs={"q": "2"})
    assert len(runner.calls) == 2
    assert runner.calls[0]["inputs"]["q"] == "1"


def test_kairos_subprocess_runner_constructs():
    runner = KairosSubprocessRunner(kairos_repo=Path("/tmp/fake-kairos"), matter_id="public")
    assert isinstance(runner, Runner)


def test_kairos_subprocess_runner_handles_missing_kairos_cli(tmp_path, monkeypatch):
    # Point PATH at an empty dir so `uv` is not findable; runner should record
    # the failure and return a RunResult with succeeded=False, not raise.
    monkeypatch.setenv("PATH", str(tmp_path))
    runner = KairosSubprocessRunner(
        kairos_repo=tmp_path, matter_id="public", uv_command="uv-does-not-exist"
    )
    result = runner.run(skill_dir=tmp_path / "skills" / "foo", inputs={})
    assert result.succeeded is False
    assert result.error is not None


def test_run_result_serializes_to_dict():
    r = RunResult(succeeded=True, output_text="out", error=None, raw={"x": 1})
    d = r.to_dict()
    assert d["succeeded"] is True
    assert d["output_text"] == "out"
    assert d["error"] is None
