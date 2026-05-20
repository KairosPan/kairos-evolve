# kairos-evolve

Self-evolution layer for the [Kairos](https://github.com/KairosPan/kairos) legal
agent studio. Extracted from `kairos/packages/harness/.../optimizer/` per the
[kairos-evolve design spec](https://github.com/KairosPan/kairos/blob/main/docs/superpowers/specs/2026-05-19-kairos-evolve-design.md).

## Status

**Phase 1 (M1.x):** L1 prompts evolution via CLI only. L2–L6 land in subsequent
phases (see spec §6.5).

## Install

```bash
pip install -e ".[cli,dev]"        # CLI + tests
pip install -e ".[api,dev]"        # FastAPI service (Phase 2+, not active in Phase 1)
```

## Quick start (L1 prompts)

```bash
# point at a local kairos checkout (must contain skills/<X>/SKILL.md)
export KAIROS_REPO=/path/to/kairos

# generate evolved prompt candidates (uses deterministic fake rewriter by default;
# pass --rewriter=dspy-gepa to invoke the real DSPy+GEPA backend)
uv run kairos-evolve prompts --skill statute-compare --iterations 3 --rewriter=fake

# Real evolution (requires OPENAI_API_KEY and dspy-ai installed):
uv run kairos-evolve prompts --skill statute-compare --iterations 10 --rewriter=dspy-gepa
```

Output lands in `output/<skill>/<timestamp>/{baseline.md, evolved.md, metrics.json}`.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
