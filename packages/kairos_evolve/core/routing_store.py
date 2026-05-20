"""SQL queries against kairos_evolve.routing_* tables.

Reads + writes are split: free functions for the common ingest/activate ops;
RoutingStore class for stateful query helpers (active-policy retrieval).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from kairos_evolve.core.time import Clock


@dataclass(frozen=True)
class RoutingEventRow:
    event_id: str
    scope_key: str
    query_hash: str
    routed_skill_id: str
    accepted_skill_id: str | None
    at: datetime


@dataclass(frozen=True)
class ActivePolicy:
    scope_key: str
    policy_version: int
    etag: str
    description_weights: dict[str, float]
    trigger_hints: dict[str, list[str]]
    activated_at: datetime


def record_routing_events(
    conn,
    events: list[RoutingEventRow],
    *,
    batch_id: uuid.UUID,
) -> int:
    """Insert routing events; deduplicate on event_id. Returns rows inserted."""
    if not events:
        return 0
    inserted = 0
    with conn.cursor() as cur:
        for ev in events:
            cur.execute(
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
                    batch_id,
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
    conn.commit()
    return inserted


def activate_policy_version(
    conn,
    *,
    scope_key: str,
    policy_version: int,
    clock: Clock,
) -> None:
    """Mark the named version as active; supersede any previously active."""
    now = clock.now()
    with conn.cursor() as cur:
        # Supersede the previously active version
        cur.execute(
            """
            UPDATE kairos_evolve.routing_policy_versions
               SET superseded_at = %s
             WHERE scope_key = %s
               AND activated_at IS NOT NULL
               AND superseded_at IS NULL
               AND policy_version <> %s
            """,
            (now, scope_key, policy_version),
        )
        # Activate the new version
        cur.execute(
            """
            UPDATE kairos_evolve.routing_policy_versions
               SET activated_at = %s, superseded_at = NULL
             WHERE scope_key = %s AND policy_version = %s
            """,
            (now, scope_key, policy_version),
        )
        # Update routing_policies pointer
        cur.execute(
            """
            INSERT INTO kairos_evolve.routing_policies
                (scope_key, active_version, last_activated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (scope_key) DO UPDATE
              SET active_version = EXCLUDED.active_version,
                  last_activated_at = EXCLUDED.last_activated_at
            """,
            (scope_key, policy_version, now),
        )
    conn.commit()


class RoutingStore:
    """Stateful query helpers (version-bump + active lookup)."""

    def __init__(self, conn, *, clock: Clock):
        self._conn = conn
        self._clock = clock

    def insert_policy_version(
        self,
        *,
        scope_key: str,
        description_weights: dict[str, float],
        trigger_hints: dict[str, list[str]],
        signed_by: str,
        signature: bytes,
        audit_id: uuid.UUID,
    ) -> int:
        """Insert a new policy_version (auto-incremented per scope_key).

        Returns the new policy_version number (BIGINT). The new version is
        STAGED (activated_at=NULL); call activate_policy_version() to flip it.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(policy_version), 0) "
                "FROM kairos_evolve.routing_policy_versions WHERE scope_key = %s",
                (scope_key,),
            )
            current_max = cur.fetchone()[0]
            new_version = current_max + 1
            etag = hashlib.sha256(
                json.dumps(description_weights, sort_keys=True).encode("utf-8")
            ).hexdigest()
            cur.execute(
                """
                INSERT INTO kairos_evolve.routing_policy_versions (
                    id, scope_key, policy_version, etag,
                    description_weights, trigger_hints,
                    signed_by, signature, audit_id
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    scope_key,
                    new_version,
                    etag,
                    json.dumps(description_weights),
                    json.dumps(trigger_hints),
                    signed_by,
                    signature,
                    audit_id,
                ),
            )
        self._conn.commit()
        return new_version

    def get_active_policy(self, scope_key: str) -> ActivePolicy | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT policy_version, etag, description_weights,
                       trigger_hints, activated_at
                  FROM kairos_evolve.routing_policy_versions
                 WHERE scope_key = %s
                   AND activated_at IS NOT NULL
                   AND superseded_at IS NULL
                """,
                (scope_key,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return ActivePolicy(
            scope_key=scope_key,
            policy_version=row[0],
            etag=row[1],
            description_weights=row[2],
            trigger_hints=row[3] if isinstance(row[3], dict) else {},
            activated_at=row[4],
        )


__all__ = [
    "ActivePolicy",
    "RoutingEventRow",
    "RoutingStore",
    "activate_policy_version",
    "record_routing_events",
]
