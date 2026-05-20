"""Idempotency storage tests against pytest-postgresql."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from kairos_evolve.core.idempotency import (
    IdempotencyCollision,
    IdempotencyHit,
    IdempotencyStore,
)
from kairos_evolve.core.time import FakeClock


def _hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def test_idempotency_miss_returns_none(evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    store = IdempotencyStore(evolve_db, clock=clock)
    assert store.get("nope") is None


def test_idempotency_store_and_retrieve(evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    store = IdempotencyStore(evolve_db, clock=clock)
    store.put(
        key="k1",
        request_hash=_hash(b'{"a": 1}'),
        response_status=200,
        response_body={"ok": True},
        ttl=timedelta(hours=1),
    )
    hit = store.get("k1")
    assert isinstance(hit, IdempotencyHit)
    assert hit.response_status == 200
    assert hit.response_body == {"ok": True}
    assert hit.request_hash == _hash(b'{"a": 1}')


def test_idempotency_replay_same_hash_returns_hit(evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    store = IdempotencyStore(evolve_db, clock=clock)
    store.put(
        key="k2",
        request_hash=_hash(b"x"),
        response_status=201,
        response_body={"id": "abc"},
        ttl=timedelta(hours=1),
    )
    hit = store.replay_if_present(key="k2", request_hash=_hash(b"x"))
    assert hit is not None
    assert hit.response_status == 201


def test_idempotency_replay_different_hash_raises_collision(evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    store = IdempotencyStore(evolve_db, clock=clock)
    store.put(
        key="k3",
        request_hash=_hash(b"first"),
        response_status=200,
        response_body=None,
        ttl=timedelta(hours=1),
    )
    try:
        store.replay_if_present(key="k3", request_hash=_hash(b"second"))
    except IdempotencyCollision as e:
        assert "k3" in str(e)
    else:
        raise AssertionError("expected IdempotencyCollision")


def test_idempotency_expired_returns_none(evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    store = IdempotencyStore(evolve_db, clock=clock)
    store.put(
        key="k4",
        request_hash=_hash(b"x"),
        response_status=200,
        response_body=None,
        ttl=timedelta(seconds=1),
    )
    clock.tick(timedelta(seconds=2))
    assert store.get("k4") is None
