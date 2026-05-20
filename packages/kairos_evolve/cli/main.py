"""Typer CLI entrypoint for `kairos-evolve`."""

from __future__ import annotations

import typer

from kairos_evolve.cli import evolve_prompts as _evolve_prompts

app = typer.Typer(
    name="kairos-evolve",
    help="Self-evolution for the Kairos legal agent studio (Phase 1: L1 prompts only).",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(_evolve_prompts.app, name="prompts", help="Evolve a skill's prompt files (L1).")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
