"""Modal deployment for kairos-evolve-api.

DEPRECATED / LEGACY SCAFFOLD. This Modal deploy predates the gateway's move to
AWS App Runner (kairos repo deploy/aws/terraform/apprunner.tf). It is the only
working deploy path TODAY, but it is pending migration: the FastAPI service
moves to AWS App Runner; the future off-request long-GEPA worker runs on
ECS-Fargate/Batch. Do not extend — see the Modal→AWS migration plan. Do not
delete until the App Runner Dockerfile + Terraform land.

Deploy:
    cd kairos-evolve
    modal deploy deploy/modal/app.py

The image installs the kairos-evolve package with [api] extras. Secrets come
from Modal's secret manager (see deploy/modal/README.md for setup).
"""

from __future__ import annotations

import modal

modal_app = modal.App("kairos-evolve-api")

# Image: install kairos-evolve[api] + cryptography from the local source.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("uv")
    .add_local_dir(local_path="../..", remote_path="/repo", copy=True)
    .run_commands(
        "cd /repo && uv pip install --system -e '.[api]'",
    )
)

# Secrets: created out-of-band via `modal secret create kairos-evolve-api ...`
secrets = [modal.Secret.from_name("kairos-evolve-api")]


@modal_app.function(
    image=image,
    secrets=secrets,
    keep_warm=1,
    concurrency_limit=10,
    timeout=60,
)
@modal.asgi_app()
def web():
    from kairos_evolve.api.app import build_app

    return build_app()
