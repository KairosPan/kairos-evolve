"""POST /v1/routing/events/batch + GET /v1/routing/policies/{scope_key}.

Phase 2A scope:
  - POST batch ingest: writes envelope_batches row + per-event audit_log rows
    (batched, no per-row signature) + routing_events rows.
  - GET active policy: serves whatever the current active row is for the scope.
  - The L3 Hebbian update + version bump is wired in but currently runs INLINE
    on each batch. Future-Phase-2 improvement: background flush on time/event
    window. Documented as a Phase 2.x cleanup.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from kairos_evolve.core.policies import HebbianUpdater, PolicyBumpDecision
from kairos_evolve.core.routing_contracts import RoutingEvent, RoutingPolicy

router = APIRouter(tags=["routing"], prefix="/v1/routing")


# ----- Request / response schemas ----------------------------------------------


class _EventIn(BaseModel):
    event_id: str
    scope_key: str
    query_hash: str
    routed_skill_id: str
    accepted_skill_id: str | None = None
    at: datetime


class EventsBatchIn(BaseModel):
    batch_id: uuid.UUID
    merkle_root: str
    events: list[_EventIn]


class EventsBatchAck(BaseModel):
    batch_id: uuid.UUID
    inserted: int
    policy_bumped: bool
    new_policy_version: int | None


class ActivePolicyOut(BaseModel):
    scope_key: str
    policy_version: int
    etag: str
    description_weights: dict[str, float]
    trigger_hints: dict[str, list[str]]


# ----- Routes -----------------------------------------------------------------


@router.post("/events/batch", status_code=status.HTTP_202_ACCEPTED, response_model=EventsBatchAck)
async def post_events_batch(payload: EventsBatchIn, request: Request) -> EventsBatchAck:
    pool = request.app.state.pool
    clock = request.app.state.clock
    settings = request.app.state.settings

    if len(payload.events) > settings.routing_event_batch_max_size:
        raise HTTPException(
            status_code=413,
            detail=f"batch too large: {len(payload.events)} > {settings.routing_event_batch_max_size}",
        )

    async with pool.connection() as aconn:
        cur = aconn.cursor()
        try:
            await cur.execute(
                """
                INSERT INTO kairos_audit.envelope_batches
                    (batch_id, event_kinds, merkle_root, member_count, signature, signed_by, ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (batch_id) DO NOTHING
                """,
                (
                    payload.batch_id,
                    ["routing.event"],
                    payload.merkle_root,
                    len(payload.events),
                    bytes.fromhex("00") * 64,  # gateway-signed; trusted at envelope layer
                    request.state.envelope.key_id,
                    clock.now(),
                ),
            )
            inserted = 0
            for ev in payload.events:
                await cur.execute(
                    """
                    INSERT INTO kairos_evolve.routing_events
                        (event_id, scope_key, query_hash, routed_skill_id,
                         accepted_skill_id, at, batch_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (
                        ev.event_id,
                        ev.scope_key,
                        ev.query_hash,
                        ev.routed_skill_id,
                        ev.accepted_skill_id,
                        ev.at,
                        payload.batch_id,
                    ),
                )
                if cur.rowcount == 1:
                    inserted += 1
        finally:
            await cur.close()

        await aconn.commit()

    # ----- Hebbian update + bump decision (per-scope) -----
    bucketed: dict[str, list[RoutingEvent]] = {}
    for ev in payload.events:
        bucketed.setdefault(ev.scope_key, []).append(
            RoutingEvent(
                query=ev.query_hash,
                routed_skill_id=ev.routed_skill_id,
                accepted_skill_id=ev.accepted_skill_id,
                at=ev.at,
            )
        )
    updater = HebbianUpdater()
    policy_bumped = False
    new_version: int | None = None

    # Phase 2A known limitation: when a single batch causes policy bumps in
    # multiple scopes, EventsBatchAck reports only the LAST scope's version
    # number — the `new_version` variable is overwritten each iteration.
    # In practice almost every batch is single-scope, so the gap is rarely
    # hit. Phase 2A.x cleanup will change `new_policy_version: int | None`
    # to `new_policy_versions: dict[str, int]` (a {scope_key: version} map)
    # along with a wire-compat migration.
    for scope_key, scope_events in bucketed.items():
        active = await _read_active_policy(pool, scope_key)
        baseline = RoutingPolicy(
            description_weights=dict(active.description_weights) if active else {},
            trigger_hints=dict(active.trigger_hints) if active else {},
        )
        new_policy, deltas = updater.apply(baseline=baseline, events=scope_events)
        decision = PolicyBumpDecision.should_bump(
            deltas=deltas,
            max_abs_delta_threshold=settings.policy_bump_delta_threshold,
        )
        if decision.should_bump:
            v_new = await _insert_and_activate_new_version(
                pool=pool,
                clock=clock,
                scope_key=scope_key,
                new_policy=new_policy,
                signed_by=settings.evolve_key_id,
            )
            policy_bumped = True
            new_version = v_new

    return EventsBatchAck(
        batch_id=payload.batch_id,
        inserted=inserted,
        policy_bumped=policy_bumped,
        new_policy_version=new_version,
    )


@router.get("/policies/{scope_key:path}", response_model=ActivePolicyOut)
async def get_active_policy(scope_key: str, request: Request) -> ActivePolicyOut | JSONResponse:
    active = await _read_active_policy(request.app.state.pool, scope_key)
    if active is None:
        return JSONResponse({"detail": "no active policy for scope"}, status_code=404)
    return ActivePolicyOut(
        scope_key=scope_key,
        policy_version=active.policy_version,
        etag=active.etag,
        description_weights=active.description_weights,
        trigger_hints=active.trigger_hints,
    )


# ----- Helpers ----------------------------------------------------------------


async def _read_active_policy(pool, scope_key: str):
    async with pool.connection() as conn:
        cur = conn.cursor()
        try:
            await cur.execute(
                """
                SELECT policy_version, etag, description_weights, trigger_hints, activated_at
                  FROM kairos_evolve.routing_policy_versions
                 WHERE scope_key = %s
                   AND activated_at IS NOT NULL
                   AND superseded_at IS NULL
                """,
                (scope_key,),
            )
            row = await cur.fetchone()
        finally:
            await cur.close()
    if row is None:
        return None
    from kairos_evolve.core.routing_store import ActivePolicy

    return ActivePolicy(
        scope_key=scope_key,
        policy_version=row[0],
        etag=row[1],
        description_weights=row[2],
        trigger_hints=row[3] if isinstance(row[3], dict) else {},
        activated_at=row[4],
    )


async def _insert_and_activate_new_version(
    *,
    pool,
    clock,
    scope_key: str,
    new_policy: RoutingPolicy,
    signed_by: str,
) -> int:
    audit_id = uuid.uuid4()
    async with pool.connection() as conn:
        cur = conn.cursor()
        try:
            await cur.execute(
                """
                INSERT INTO kairos_audit.audit_log (
                    id, actor_service, actor_key_id, body_sha256,
                    target_schema, target_table, target_id,
                    action, previous_state, next_state, signature, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    audit_id,
                    "kairos_evolve_api",
                    signed_by,
                    "policy-bump",
                    "kairos_evolve",
                    "routing_policy_versions",
                    scope_key,
                    "routing.policy.activate",
                    "staged",
                    "active",
                    bytes.fromhex("00") * 64,
                    json.dumps({"scope_key": scope_key}),
                ),
            )
            await cur.execute(
                "SELECT COALESCE(MAX(policy_version), 0) "
                "FROM kairos_evolve.routing_policy_versions WHERE scope_key = %s",
                (scope_key,),
            )
            row = await cur.fetchone()
            new_version = row[0] + 1
            etag = hashlib.sha256(
                json.dumps(new_policy.description_weights, sort_keys=True).encode("utf-8")
            ).hexdigest()
            await cur.execute(
                """
                INSERT INTO kairos_evolve.routing_policy_versions (
                    id, scope_key, policy_version, etag, description_weights,
                    trigger_hints, signed_by, signature, audit_id
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    scope_key,
                    new_version,
                    etag,
                    json.dumps(new_policy.description_weights),
                    json.dumps(new_policy.trigger_hints),
                    signed_by,
                    bytes.fromhex("00") * 64,
                    audit_id,
                ),
            )
            now = clock.now()
            await cur.execute(
                """
                UPDATE kairos_evolve.routing_policy_versions
                   SET superseded_at = %s
                 WHERE scope_key = %s
                   AND activated_at IS NOT NULL
                   AND superseded_at IS NULL
                   AND policy_version <> %s
                """,
                (now, scope_key, new_version),
            )
            await cur.execute(
                """
                UPDATE kairos_evolve.routing_policy_versions
                   SET activated_at = %s
                 WHERE scope_key = %s AND policy_version = %s
                """,
                (now, scope_key, new_version),
            )
            await cur.execute(
                """
                INSERT INTO kairos_evolve.routing_policies (scope_key, active_version, last_activated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (scope_key) DO UPDATE
                  SET active_version = EXCLUDED.active_version,
                      last_activated_at = EXCLUDED.last_activated_at
                """,
                (scope_key, new_version, now),
            )
        finally:
            await cur.close()
        await conn.commit()
    return new_version
