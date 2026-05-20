"""POST /v1/jobs/finished — Phase 2A stub.

Phase 3 fills this in with: verify K_inngest envelope, verify K_job manifest
signature, run constraints, transition job_outputs.verification_status, create
skill_change_proposals row, write audit, SSE-notify gateway.

For Phase 2A the route exists so the L3 wiring can validate the envelope flow
end-to-end without blocking on Phase 3 work.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["jobs"])


@router.post("/v1/jobs/finished", status_code=status.HTTP_202_ACCEPTED)
async def jobs_finished() -> JSONResponse:
    """Stub: accept signed envelope, return 202. Real handler arrives in Phase 3."""
    return JSONResponse({"status": "accepted", "phase": "stub"}, status_code=202)
