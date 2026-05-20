# kairos-evolve

Self-evolution layer for the [Kairos](https://github.com/KairosPan/kairos)
legal agent studio. Phase 1 ships the L1 prompts evolution CLI.

Authoritative design:
[kairos-evolve design spec](https://github.com/KairosPan/kairos/blob/main/docs/superpowers/specs/2026-05-19-kairos-evolve-design.md).

## Status

- **Phase 1 (this release):** L1 prompts evolution via CLI.
- **Phase 2+** (L2 retrieval / L3 routing / L4 models / L5 synthesis / L6 selfmod):
  see spec §6.5.

## Install

```bash
git clone https://github.com/KairosPan/kairos-evolve.git
cd kairos-evolve
uv venv .venv --python 3.12
uv pip install -e ".[cli,dev]"
```

`[api]` extras are reserved for Phase 2+ (FastAPI service surface) and not
used by anything in this release.

## Quick start

Point `KAIROS_REPO` at a local checkout of the kairos main repo (the repo
that holds the actual `skills/<name>/SKILL.md` files you want to evolve):

```bash
export KAIROS_REPO=/path/to/kairos
```

Generate evolved-prompt candidates with the deterministic fake rewriter
(no LLM, no cost — useful for smoke-testing the full pipeline):

```bash
uv run kairos-evolve prompts --skill statute-compare --iterations 3 --rewriter fake
```

Real DSPy + GEPA evolution against your chosen LLM:

```bash
export OPENAI_API_KEY=sk-...
uv run kairos-evolve prompts \
    --skill statute-compare \
    --iterations 10 \
    --rewriter dspy-gepa \
    --eval-model openai/gpt-4.1-mini \
    --runner kairos-subprocess
```

Output lands in `output/<skill>/<timestamp>/`:

```
output/statute-compare/20260519_120000/
├── baseline.md          original prompt
├── evolved.md           winning candidate (if any beat baseline)
└── metrics.json         baseline / evolved scores + per-candidate explored
```

Review the diff and decide whether to land the change in kairos main (Phase
1 deliberately does not auto-write back; that comes with the gateway
integration in a later phase).

## Testing

```bash
uv run pytest -v
```

The cross-repo envelope contract tests in `tests/contract/` require
`shared/envelope/v1/*.json` to be in sync with kairos main. Refresh with:

```bash
KAIROS_REPO=/path/to/kairos ./scripts/regen-contracts.sh
```

## Layout

```
packages/kairos_evolve/
├── core/                 domain logic — pure, no FastAPI/Typer/Modal
│   ├── config.py         EvolveConfig + KAIROS_REPO resolution
│   ├── envelope.py       ed25519 wire envelope (peer of kairos main)
│   ├── contracts.py      re-exports (Phase 1: EnvelopeV1 only)
│   ├── skill_io.py       read SKILL.md + prompts/
│   ├── constraints.py    universal + skill artifact gates
│   ├── fitness.py        FitnessResult + pure metrics
│   ├── judges.py         DSPy LLMJudge (lazy import)
│   ├── runner.py         Runner Protocol + KairosSubprocessRunner
│   └── prompts.py        L1 evolve_prompts loop
└── cli/                  Typer entry; depends on core only
    ├── main.py
    └── evolve_prompts.py
```

## License

Apache-2.0 — see [LICENSE](./LICENSE).
