"""FastAPI middleware that verifies the X-Envelope-* headers on POST requests.

Behavior:
  - GET / HEAD / OPTIONS: skip (no envelope required).
  - POST / PUT / PATCH / DELETE on paths NOT in BYPASS_PATHS:
      verify the envelope against the registered public key for the
      X-Envelope-Key-Id, then call next.
  - On failure: 401 JSON `{"detail": "<reason>"}`.

The public key registry is provided via app.state.public_keys (a
{key_id: Ed25519PublicKey} mapping populated at startup).
"""

from __future__ import annotations

import json
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from kairos_evolve.core.envelope import (
    EnvelopeV1,
    EnvelopeVerifyError,
    verify_envelope,
)

BYPASS_PATHS = {"/healthz", "/readyz"}

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class EnvelopeVerifyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in WRITE_METHODS:
            return await call_next(request)
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        public_keys: dict[str, Ed25519PublicKey] = request.app.state.public_keys

        try:
            envelope = _envelope_from_headers(request)
        except (KeyError, ValueError) as exc:
            return _err(status.HTTP_401_UNAUTHORIZED, f"envelope header missing/invalid: {exc}")

        if envelope.key_id not in public_keys:
            return _err(
                status.HTTP_401_UNAUTHORIZED,
                f"unknown key_id {envelope.key_id!r}",
            )

        # Read body bytes — must be done carefully since the body is a stream.
        body_bytes = await request.body()
        try:
            body_obj = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except json.JSONDecodeError as exc:
            return _err(status.HTTP_401_UNAUTHORIZED, f"body not JSON: {exc}")

        try:
            verify_envelope(envelope, body=body_obj, public_key=public_keys[envelope.key_id])
        except EnvelopeVerifyError as exc:
            return _err(status.HTTP_401_UNAUTHORIZED, f"envelope verify failed: {exc}")

        # Stash the verified envelope on request.state for handlers + audit.
        request.state.envelope = envelope
        request.state.body_obj = body_obj
        return await call_next(request)


def _envelope_from_headers(request: Request) -> EnvelopeV1:
    h = request.headers
    return EnvelopeV1(
        version=h["x-envelope-version"],
        key_id=h["x-envelope-key-id"],
        service_id=h["x-envelope-service-id"],
        ts=datetime.fromisoformat(h["x-envelope-ts"]),
        nonce=h["x-envelope-nonce"],
        body_sha256=h["x-envelope-body-sha256"],
        signature=h["x-envelope-signature"],
    )


def _err(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code)


__all__ = ["BYPASS_PATHS", "WRITE_METHODS", "EnvelopeVerifyMiddleware"]
