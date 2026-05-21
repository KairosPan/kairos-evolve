"""POST /v1/routing/events/batch + GET /v1/routing/policies/{scope_key}.

Phase 2A scope:
  - POST batch ingest: writes envelope_batches row + routing_events rows.
  - GET active policy: serves whatever the current active row is for the scope.
  - The L3 Hebbian update + version bump runs INLINE on each batch. Future
    improvement: background flush on time/event window.

Persistence layer: this module uses the async helpers in ``core.audit``
(``AsyncAuditWriter``) and ``core.routing_store``
(``AsyncRoutingStore``, ``async_record_routing_events``,
``async_activate_policy_version``). The inline SQL that previously
duplicated those helpers' bodies has been removed (Phase 2A.x cleanup).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from kairos_evolve.core.audit import AsyncAuditWriter, AuditEntry
from kairos_evolve.core.policies import HebbianUpdater, PolicyBumpDecision
from kairos_evolve.core.routing_contracts import RoutingEvent, RoutingPolicy
from kairos_evolve.core.routing_store import (
    ActivePolicy,
    AsyncRoutingStore,
    RoutingEventRow,
    async_activate_policy_version,
    async_record_routing_events,
)
from kairos_evolve.core.time import Clock

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
    """Ack returned by ``POST /v1/routing/events/batch``.

    ``new_policy_versions`` is the canonical multi-scope answer: a
    ``{scope_key: new_policy_version}`` dict that captures every scope
    whose policy was bumped by this batch (Phase 2A.x cleanup).

    ``new_policy_version`` is preserved as a deprecated alias for the
    single-scope case: when the dict has exactly one entry, the field
    is populated with that value; otherwise it is ``None`` (the field
    cannot honestly report "the" new version when several were bumped,
    and ambiguity is worse than absence). Old clients that read only
    ``new_policy_version`` continue to work for the common single-scope
    case; clients that need the full picture should read
    ``new_policy_versions``. The field will be removed in Phase 2C.
    """

    batch_id: uuid.UUID
    inserted: int
    policy_bumped: bool
    new_policy_versions: dict[str, int] = {}
    new_policy_version: int | None = None  # deprecated — see class docstring


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
    clock: Clock = request.app.state.clock
    settings = request.app.state.settings

    if len(payload.events) > settings.routing_event_batch_max_size:
        raise HTTPException(
            status_code=413,
            detail=(
                f"batch too large: {len(payload.events)} > {settings.routing_event_batch_max_size}"
            ),
        )

    async with pool.connection() as aconn:
        audit = AsyncAuditWriter(aconn, clock=clock)
        await audit.write_envelope_only(
            batch_id=payload.batch_id,
            merkle_root=payload.merkle_root,
            member_count=len(payload.events),
            batch_signature=bytes.fromhex("00") * 64,  # trusted at envelope layer
            signed_by=request.state.envelope.key_id,
            event_kinds=["routing.event"],
        )
        event_rows = [
            RoutingEventRow(
                event_id=ev.event_id,
                scope_key=ev.scope_key,
                query_hash=ev.query_hash,
                routed_skill_id=ev.routed_skill_id,
                accepted_skill_id=ev.accepted_skill_id,
                at=ev.at,
            )
            for ev in payload.events
        ]
        inserted = await async_record_routing_events(aconn, event_rows, batch_id=payload.batch_id)

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
    # Phase 2A.x cleanup: track every scope that bumped. Multi-scope batches
    # used to lose all but the last bump in the ack; now every bump is
    # surfaced. See `EventsBatchAck` docstring for the wire-compat story.
    new_versions: dict[str, int] = {}

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
            v_new = await _bump_and_activate(
                pool=pool,
                clock=clock,
                scope_key=scope_key,
                new_policy=new_policy,
                signed_by=settings.evolve_key_id,
            )
            new_versions[scope_key] = v_new

    # Deprecated single-version field: only set when exactly one scope
    # bumped (otherwise ambiguity would lie about "the" new version).
    legacy_new_version: int | None = (
        next(iter(new_versions.values())) if len(new_versions) == 1 else None
    )

    return EventsBatchAck(
        batch_id=payload.batch_id,
        inserted=inserted,
        policy_bumped=bool(new_versions),
        new_policy_versions=new_versions,
        new_policy_version=legacy_new_version,
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


async def _read_active_policy(pool, scope_key: str) -> ActivePolicy | None:
    """Read the active policy via the async store. No clock is needed for the
    read path — pass the real one for symmetry with the write path."""
    from kairos_evolve.core.time import RealClock

    async with pool.connection() as aconn:
        store = AsyncRoutingStore(aconn, clock=RealClock())
        return await store.get_active_policy(scope_key)


async def _bump_and_activate(
    *,
    pool,
    clock: Clock,
    scope_key: str,
    new_policy: RoutingPolicy,
    signed_by: str,
) -> int:
    """Audit-log the policy bump, insert the staged version, then activate it.

    Replaces the previous inline SQL block. Uses the async helpers so the
    same logic now lives in one place (``AsyncAuditWriter`` /
    ``AsyncRoutingStore`` / ``async_activate_policy_version``); future
    behaviour changes to the bump pipeline touch the helpers, not the
    route handler.
    """
    async with pool.connection() as aconn:
        audit = AsyncAuditWriter(aconn, clock=clock)
        store = AsyncRoutingStore(aconn, clock=clock)

        audit_id = await audit.write_signed(
            AuditEntry(
                actor_service="kairos_evolve_api",
                actor_key_id=signed_by,
                body_sha256="policy-bump",
                target_schema="kairos_evolve",
                target_table="routing_policy_versions",
                target_id=scope_key,
                action="routing.policy.activate",
                payload={"scope_key": scope_key},
                previous_state="staged",
                next_state="active",
            ),
            signature=bytes.fromhex("00") * 64,
        )
        new_version = await store.insert_policy_version(
            scope_key=scope_key,
            description_weights=new_policy.description_weights,
            trigger_hints=new_policy.trigger_hints,
            signed_by=signed_by,
            signature=bytes.fromhex("00") * 64,
            audit_id=audit_id,
        )
        await async_activate_policy_version(
            aconn, scope_key=scope_key, policy_version=new_version, clock=clock
        )
    return new_version
