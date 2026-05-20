"""Health endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_healthz_returns_200(asgi_client):
    resp = await asgi_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_returns_200_when_db_reachable(asgi_client):
    resp = await asgi_client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["db"] == "ok"
