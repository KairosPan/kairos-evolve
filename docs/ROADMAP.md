# kairos-evolve roadmap

Rolling future-development plan for the self-evolution layer of [Kairos](https://github.com/KairosPan/kairos).

Authoritative design: [`docs/superpowers/specs/2026-05-19-kairos-evolve-design.md`](https://github.com/KairosPan/kairos/blob/main/docs/superpowers/specs/2026-05-19-kairos-evolve-design.md) (in the kairos main repo). Phase plans live in kairos main under `docs/superpowers/plans/`.

Last refresh: 2026-05-20.

---

## What kairos-evolve is

A separate Python service + library responsible for the **L1–L6 optimizer** layers of the legal agent studio. Cross-repo integration happens through signed ed25519 envelopes shared at `shared/envelope/v1/` (synchronized between kairos main and kairos-evolve via `scripts/regen-contracts.sh`).

The split between this repo and kairos main:

| Concern | Lives in |
| --- | --- |
| Hosted product (Studio UI, Harness, Gateway, Workflow Engine, Sandbox) | [kairos main](https://github.com/KairosPan/kairos) |
| Default skill library + connectors | kairos main |
| Optimizer L1 prompts evolution (CLI + DSPy/GEPA) | **kairos-evolve** (this repo) |
| Optimizer L3 routing service (`evolve-api` on AWS App Runner — `deploy/aws/`, matching the gateway) | **kairos-evolve** (this repo) |
| Optimizer L3 client + dispatch (in-process inside kairos main's harness) | kairos main (`packages/harness/src/kairos_harness/optimizer/client/`) |
| Future L2 retrieval / L4 models / L5 synthesis / L6 selfmod | **kairos-evolve** (this repo) |
| Envelope wire format (ed25519 sign/verify, Merkle) | both repos (peer implementations, contract-tested) |

---

## Status by optimizer level

### L1 — prompts evolution ✅ Shipped

Per-skill `prompts/*.md` evolution via DSPy + GEPA. Implemented as a CLI (`kairos-evolve prompts`) that:

1. Reads `SKILL.md` + prompts/ from a local kairos-main checkout (via `KAIROS_REPO`).
2. Generates candidate prompt variations with a configurable rewriter (deterministic `fake` for smoke; `dspy-gepa` against an LLM).
3. Evaluates each candidate against the skill's golden set using the chosen runner (default: subprocess into the kairos main CLI).
4. Writes baseline + best-evolved + per-candidate metrics to `output/<skill>/<timestamp>/`.

The CLI deliberately does not auto-write evolved prompts back into kairos main; humans review the diff and decide.

**Next on L1:**
- LLMJudge / pairwise-preference scorer that complements the current `keyword_overlap + length_penalty` fitness (already a placeholder slot via `judges.py`).
- Multi-skill batch mode for a CI-style "evolve every changed skill" pass.
- Auto-write-back path will land alongside the L3 cutover (Phase 2B), so a single gateway-side credential covers both L1 and L3 writes.

### L3 — routing 🟡 Phase 2A done, Phase 2B in plan

L3 chooses which adapter / model gets a given step, scoped per `(skill, jurisdiction, …)`. Two-side architecture:

- **Service side (`evolve-api`)** — FastAPI on AWS App Runner (`deploy/aws/`, matching the kairos gateway), owns `routing_policy_versions`, `routing_events`, `kairos_audit.idempotency_keys`. Accepts signed envelopes; emits `policy-invalidated` webhooks.
- **Client side (in kairos main)** — `EnvelopeSigner` (K_gw), `EvolveApiClient` (sync httpx), `RoutingCache` (in-process `scope_key → ActivePolicy`), `RemoteOptimizerL3` (drop-in for the in-tree `OptimizerL3`).

| Phase | What ships | Status |
| --- | --- | --- |
| **Phase 2A** | `evolve-api` service (shipped Modal-deployable in PR #1; now deployed on **AWS App Runner** — `deploy/aws/`), signed envelopes, routing-event ingestion, policy versioning, contract tests against kairos-main DDL fixtures | ✅ Merged (this repo PR #1) |
| **Phase 2B** | kairos-main thin client tree + flag dispatch + gateway webhook middleware + `policy-invalidated` route + DEPLOY.md rollout | 🟡 Plan in kairos main PR #8; 16 implementation PRs to follow |
| **Phase 2C (planned)** | Flag flip from `KAIROS_OPTIMIZER_REMOTE=0` to `=1` as default; in-tree `OptimizerL3` removal | 🔵 Scheduled after one week of clean staging on Phase 2B |

Phase 2B open questions (raised during PR #8 plan review):
- **Idempotency-key derivation rule** for `EvolveApiClient` retries — needs to be specified in the plan so retries are idempotent at the service.
- **Rollback during in-flight remote call** — if the flag is flipped from 1→0 mid-call, the remote completes and the in-tree path on the next request sees no accumulated state. Should be documented as expected.
- **Webhook delivery ordering** — `policy-invalidated` events must be ordered (or version-checked at the cache) so a delayed older event cannot evict a newer policy.
- **RoutingCache cold-start** — `RemoteOptimizerL3` behavior on first call before the cache has an `ActivePolicy` needs a documented policy (block-on-fetch with a deadline, or 1.0-weight default until populated).

### L2 — retrieval 🔵 Design

Optimizer over RAG pipelines: hybrid retrieval weights, reranker selection, chunk-size policy, per-jurisdiction corpus routing.

Targeted after L3 Phase 2C completes — L3's `evolve-api` service surface is the template for L2's service shape, and L2 reuses the same envelope + signed-webhook plumbing. Open design questions:

- Does kairos-evolve own its own pgvector store, or does it query into kairos main's via a read-only credential?
- Eval set provenance — are RAG eval cases stored alongside skill golden cases, or in a separate `retrieval_eval_sets` table?
- Serialization format for "a retrieval pipeline" (the analog of `prompts/*.md` for L1).

### L4 — models 🔵 Design

Adapter selection (Claude vs DeepSeek vs OpenAI) and lightweight fine-tuning candidates. Depends on L3 routing observability + L2 retrieval observability data to score candidates.

### L5 — synthesis 🔵 Design

New skill composition from trace patterns. Reads from the kairos main `improvement-detector` proposal stream and proposes new `SKILL.md + prompts/ + schemas/ + evals/` directories for human review.

### L6 — selfmod 🔵 Design

Proposal → review → merge for kairos-evolve itself (the L6 layer evolves the evolution layer). Gated behind an L5-class review surface plus an additional safety review for self-modifying code.

---

## Cross-repo coordination

- **Envelope wire format** is shared. Both repos check the same fixtures into `shared/envelope/v1/`. `scripts/regen-contracts.sh` (this repo) and the contract tests in both repos enforce byte equivalence.
- **DDL contract**: kairos main migration `0210_kairos_evolve_schemas.sql` and kairos-evolve `tests/sql/ddl_phase2a.sql` must stay equivalent. A regen script + CI gate is planned as part of Phase 2B.
- **Versioning**: when the envelope schema bumps, both repos must release together. There is no `v2` envelope shipping unilaterally.

---

## How this roadmap is maintained

- Update the per-level status whenever a phase tag moves (e.g., `kairos-evolve-phase{N}-v1`).
- Mirror the L3 status updates from kairos main's [`docs/ROADMAP.md`](https://github.com/KairosPan/kairos/blob/main/docs/ROADMAP.md) when its Phase 2B cutover advances.
- Keep absolute dates in the "Last refresh" line.

If a level is descoped, leave its row with a 🧊 marker and a link to the decision record.
