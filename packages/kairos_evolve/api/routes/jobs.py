"""POST /v1/jobs/run — Slice 9 (#34) candidate-return producer.

The flag-gated OUTSIDE compute seam's evolve-side endpoint. The kairos
``RemoteEvolveExecutor`` signs a D11-clean job body and POSTs it here; this
handler:

  1. is verified by ``EnvelopeVerifyMiddleware`` (the gateway-signed body lands
     on ``request.state.body_obj``) + de-duped by ``IdempotencyMiddleware`` (key
     from the inbound ``job_id``) — ZERO per-route auth code;
  2. runs the FAKE evolve compute synchronously (``core.fake_evolve.run_fake_evolve``
     — fake rewriter + heuristic scorer, no DSPy / no kairos checkout; real
     GEPA + Runner is #35);
  3. signs a K_evolve ``CandidateReturn`` envelope (candidate_text + evidence +
     org binding, matter-free) and POSTs it to the gateway
     ``/v1/webhooks/jobs-finished`` intake (reuses ``GatewayEventsClient``);
  4. on a push non-2xx returns 502 so the caller's job backs off + retries
     (delivery durability via the job queue, not new infra; spec D3). On success
     returns 202 + a handle.

Safety: this service NEVER adopts anything — the candidate lands ``pending`` at
the intake (D10). This handler only computes + returns.

The legacy ``/v1/jobs/finished`` stub is left in place (vestigial; a future
Inngest-style completion callback may reclaim it).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from kairos_evolve.core.fake_evolve import run_fake_evolve

router = APIRouter(tags=["jobs"])


@router.post("/v1/jobs/run")
async def jobs_run(request: Request) -> JSONResponse:
    """Verify (middleware) → run fake evolve → sign + push candidate to gateway."""
    body = request.state.body_obj
    job_id = body["job_id"]
    org_id = body["org_id"]
    # ``target_ref`` is the skill identifier the candidate is scoped to; the
    # body is D11-clean so this is an id, not prompt text.
    skill_id = body.get("target_ref") or body.get("skill_id") or ""

    # --- (fake) compute, synchronously inside the handler (spec D2) ---
    result = run_fake_evolve(skill_id=skill_id)
    # Prefer a strict winner; fall back to the best explored candidate so the
    # returned body always carries non-empty candidate_text (the candidate is
    # only ever a human-reviewed ``pending`` proposal — D10).
    chosen = result.winner
    if chosen is None and result.candidates_explored:
        chosen, _ = max(result.candidates_explored, key=lambda pair: pair[1])
    candidate_text = chosen.new_text if chosen is not None else result.baseline_text

    evidence = {
        "baseline_score": result.baseline_score,
        "evolved_score": result.evolved_score,
        "improvement": result.evolved_score - result.baseline_score,
        "winner_rationale": result.winner.rationale if result.winner else None,
        "candidates_explored": len(result.candidates_explored),
        "compute": "fake",  # #34 ships the fake rewriter; real GEPA is #35
    }
    # No real spend in the fake path — be honest about it.
    spend_usd = 0.0

    # --- sign K_evolve candidate + push to the gateway intake ---
    gateway = request.app.state.gateway_events
    status_code = await gateway.candidate_returned(
        job_id=job_id,
        org_id=org_id,
        skill_id=skill_id,
        candidate_text=candidate_text,
        evidence=evidence,
        spend_usd=spend_usd,
    )
    if status_code >= 400:
        # Delivery failed: fail closed so the caller's job retries the dispatch
        # (the candidate must never silently vanish; spec D3).
        return JSONResponse(
            {"detail": f"candidate delivery to gateway failed ({status_code})", "job_id": job_id},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    return JSONResponse(
        {"status": "accepted", "job_id": job_id},
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.post("/v1/jobs/finished", status_code=status.HTTP_202_ACCEPTED)
async def jobs_finished() -> JSONResponse:
    """Vestigial stub (pre-#34). Left in place; a future completion callback may
    reclaim it. The live candidate-return path is ``/v1/jobs/run`` above."""
    return JSONResponse({"status": "accepted", "phase": "stub"}, status_code=202)
