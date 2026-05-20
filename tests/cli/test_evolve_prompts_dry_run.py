"""CLI smoke test — uses fake rewriter + fake runner, writes output to tmp."""

from __future__ import annotations

import json
import subprocess
import sys


def test_cli_dry_run_writes_output(fake_kairos_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_REPO", str(fake_kairos_repo))
    out_dir = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kairos_evolve.cli.main",
            "prompts",
            "--skill",
            "statute-compare",
            "--iterations",
            "2",
            "--rewriter",
            "fake",
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "wrote" in result.stdout.lower() or "saved" in result.stdout.lower()
    runs = sorted(out_dir.glob("statute-compare/*"))
    assert runs, f"no run dir under {out_dir}, stdout={result.stdout}, stderr={result.stderr}"
    run_dir = runs[-1]
    assert (run_dir / "baseline.md").is_file()
    assert (run_dir / "metrics.json").is_file()
    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert metrics["skill_name"] == "statute-compare"
    assert "baseline_score" in metrics
    assert "evolved_score" in metrics


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "kairos_evolve.cli.main", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "kairos-evolve" in result.stdout.lower() or "prompts" in result.stdout.lower()
