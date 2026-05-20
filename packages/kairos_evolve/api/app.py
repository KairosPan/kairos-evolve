"""FastAPI app assembly: settings → pool → public-key registry → middleware → routes.

Exposed as `build_app() -> FastAPI` so tests can construct fresh instances.
Modal deploy imports `app` from this module.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fastapi import FastAPI

from kairos_evolve.api.adapters.gateway_events import GatewayEventsClient
from kairos_evolve.api.adapters.neon import build_pool
from kairos_evolve.api.middleware.envelope_verify import EnvelopeVerifyMiddleware
from kairos_evolve.api.middleware.idempotency import IdempotencyMiddleware
from kairos_evolve.api.routes import health, jobs, routing
from kairos_evolve.api.settings import Settings
from kairos_evolve.core.time import RealClock


def build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings()
        app.state.settings = settings
        app.state.clock = RealClock()

        # Build the Postgres pool
        app.state.pool = await build_pool(settings.neon_url)

        # Build the public key registry (only gateway for now; Phase 2B may add
        # more keys e.g. K_inngest when the jobs route is filled in).
        gw_pub = Ed25519PublicKey.from_public_bytes(settings.gateway_public_key_bytes)
        app.state.public_keys = {settings.gateway_key_id: gw_pub}

        # Build the evolve private key + webhook client
        evolve_priv = Ed25519PrivateKey.from_private_bytes(settings.evolve_private_key_bytes)
        app.state.gateway_events = GatewayEventsClient(
            base_url=settings.gateway_base_url,
            evolve_private_key=evolve_priv,
            evolve_key_id=settings.evolve_key_id,
            clock=app.state.clock,
        )

        yield

        # Tear down
        await app.state.gateway_events.aclose()
        await app.state.pool.close()

    app = FastAPI(title="kairos-evolve-api", version="0.2.0-phase2a", lifespan=lifespan)

    # Middleware: idempotency runs INSIDE envelope_verify (closer to handler).
    # Starlette runs middleware bottom-up on entry and top-down on exit.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(EnvelopeVerifyMiddleware)

    # Routes
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(routing.router)

    return app


# Module-level None — Modal deploy imports build_app() and calls it
app = None
