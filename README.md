# kairos-evolve

Self-evolution layer for the [Kairos](https://github.com/KairosPan/kairos)
legal agent studio. Implements the L1–L6 optimizer levels described in
[the design spec](https://github.com/KairosPan/kairos/blob/main/docs/superpowers/specs/2026-05-19-kairos-evolve-design.md).

## Status

| Level | What it evolves | Status |
| --- | --- | --- |
| **L1 prompts** | per-skill `prompts/*.md` via DSPy/GEPA | ✅ Shipped — CLI (`kairos-evolve prompts …`) |
| **L3 routing — service** | `evolve-api` (FastAPI on Modal) | ✅ Shipped — Phase 2A (PR #1) |
| **L3 routing — kairos integration** | thin client + signed webhooks in kairos main | 🟡 Phase 2B — plan landed in kairos main PR #8; cutover PRs to follow. Flag `KAIROS_OPTIMIZER_REMOTE` defaults OFF until soak completes |
| **L2 retrieval** | RAG weights + hybrid retrieval | 🔵 Design (spec §6.5) |
| **L4 models** | adapter selection + fine-tuning | 🔵 Design |
| **L5 synthesis** | new skill composition from trace patterns | 🔵 Design |
| **L6 selfmod** | proposal → review → merge for kairos-evolve itself | 🔵 Design |

See [`docs/ROADMAP.md`](./docs/ROADMAP.md) for the rolling future-development plan.

## Install

```bash
git clone https://github.com/KairosPan/kairos-evolve.git
cd kairos-evolve
uv venv .venv --python 3.12
uv pip install -e ".[cli,dev]"

# Phase 2A+ — install the API extra to run/deploy evolve-api:
uv pip install -e ".[cli,api,dev]"
```

## L1 — prompts evolution (CLI)

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
output/statute-compare/20260520_120000/
├── baseline.md          original prompt
├── evolved.md           winning candidate (if any beat baseline)
└── metrics.json         baseline / evolved scores + per-candidate explored
```

Review the diff and decide whether to land the change in kairos main. L1 deliberately does not auto-write back; the gateway-side write path comes online with the L3 Phase 2B cutover.

## L3 — routing (Phase 2A: evolve-api service)

The L3 routing service ships as a FastAPI app deployable to Modal (one container per region). It accepts signed ed25519 envelopes from kairos main, decides routing-policy updates from observed traces, and broadcasts policy invalidation webhooks back.

```bash
# Local dev
uv run uvicorn kairos_evolve.api.app:app --reload

# Modal deploy
modal deploy packages/kairos_evolve/api/modal_app.py
```

The Phase 2B kairos-main integration is the cross-repo cutover. Until that lands and bakes in staging, kairos main keeps its in-tree `OptimizerL3` (flag `KAIROS_OPTIMIZER_REMOTE=0` — the default). The Phase 2B plan is at [kairos PR #8](https://github.com/KairosPan/kairos/pull/8); the implementation PRs follow as 16 task-sized merges.

## Testing

```bash
uv run pytest -v
```

The cross-repo envelope contract tests in `tests/contract/` require
`shared/envelope/v1/*.json` to be in sync with kairos main. Refresh with:

```bash
KAIROS_REPO=/path/to/kairos ./scripts/regen-contracts.sh
```

CI runs the contract tests against the checked-in fixtures; the regen script is for local refresh after kairos main updates the envelope schema.

## Layout

```
packages/kairos_evolve/
├── core/                 domain logic — pure, no FastAPI/Typer/Modal
│   ├── config.py         EvolveConfig + KAIROS_REPO resolution
│   ├── envelope.py       ed25519 wire envelope (peer of kairos main)
│   ├── contracts.py      re-exports (EnvelopeV1, RoutingPolicy, …)
│   ├── skill_io.py       read SKILL.md + prompts/
│   ├── constraints.py    universal + skill artifact gates
│   ├── fitness.py        FitnessResult + pure metrics
│   ├── judges.py         DSPy LLMJudge (lazy import)
│   ├── runner.py         Runner Protocol + KairosSubprocessRunner
│   ├── prompts.py        L1 evolve_prompts loop
│   └── routing/          L3 routing decision logic (Phase 2A)
├── api/                  evolve-api — FastAPI service + Modal entrypoint (Phase 2A)
│   ├── app.py
│   └── modal_app.py
├── cli/                  Typer entry; depends on core only
│   ├── main.py
│   └── evolve_prompts.py
└── scripts/
    └── regen-contracts.sh
```

`core/` stays pure (no FastAPI/Typer/Modal imports) so the L1 CLI, the L3 service, and any future synthesis worker can compose the same domain logic without pulling in framework deps.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
