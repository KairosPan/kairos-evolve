# kairos-evolve-api on Modal

> **STATUS: LEGACY / CURRENT SCAFFOLD.** The kairos gateway moved to AWS App
> Runner (kairos repo `deploy/aws/`); kairos-evolve-api was never migrated and
> still runs on Modal via this procedure. This is the live path but pending the
> Modal→AWS migration (App Runner for the FastAPI service via a Dockerfile + ECR
> + Terraform mirroring the gateway, Secrets Manager replacing the Modal/Infisical
> secret; ECS-Fargate/Batch for the future long-GEPA worker). The steps below
> remain accurate for the existing Modal deploy — do NOT rewrite the `modal
> secret create` / `modal deploy` / `*.modal.run` / `modal app rollback` steps to
> AWS verbs (no App Runner service, Secrets Manager entries, or AWS URL exist yet).
> The ed25519 keygen recipe and the "public keys go in BOTH the secret AND the
> kairos-gateway env" instruction below are platform-neutral and reused by the
> AWS plan. See the Modal→AWS App Runner migration plan.

## Prerequisites

1. Modal account + CLI installed: `pip install modal && modal token new`
2. Neon project with kairos_evolve + kairos_audit schemas applied
   (Phase 2A applies these via `tests/sql/ddl_phase2a.sql`; Plan 2B
   replaces this with an Alembic migration in the kairos main repo).
3. ed25519 keypairs generated for K_evolve and K_gw (see below).

## Generate ed25519 keys (one-time)

```bash
python -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
for name in ('K_evolve', 'K_gw'):
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes_raw().hex()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    print(f'{name}_PRIVATE={priv_hex}')
    print(f'{name}_PUBLIC={pub_hex}')
    print()
"
```

Store the private keys somewhere safe (Infisical, 1Password, etc.). The
public keys go in BOTH this Modal secret AND the kairos-gateway env (which
needs to know evolve's public key to verify webhooks — Plan 2B).

## Create the Modal secret

```bash
modal secret create kairos-evolve-api \
  KAIROS_EVOLVE_DATABASE_URL="postgresql://user:pass@host/db?sslmode=require" \
  KAIROS_EVOLVE_KEY_ID="K_evolve" \
  KAIROS_EVOLVE_PRIVATE_KEY_HEX="<from above>" \
  KAIROS_EVOLVE_GATEWAY_BASE_URL="https://gateway.example.com" \
  KAIROS_GATEWAY_KEY_ID="K_gw" \
  KAIROS_GATEWAY_PUBLIC_KEY_HEX="<from above>"
```

## Deploy

```bash
modal deploy deploy/modal/app.py
```

Modal prints the URL (e.g.,
`https://yourusername--kairos-evolve-api-web.modal.run`). Verify:

```bash
curl https://yourusername--kairos-evolve-api-web.modal.run/healthz
# → {"status":"ok"}

curl https://yourusername--kairos-evolve-api-web.modal.run/readyz
# → {"status":"ok","db":"ok"}
```

## Smoke-test a signed POST

```bash
python -c "
import httpx
from datetime import datetime, UTC
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kairos_evolve.core.envelope import sign_envelope

priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex('<K_gw_PRIVATE>'))
body = {'batch_id': '00000000-0000-0000-0000-000000000001', 'merkle_root': 'm', 'events': []}
env = sign_envelope(body=body, key=priv, key_id='K_gw', service_id='kairos-gateway')
headers = {
    'X-Envelope-Version': env.version, 'X-Envelope-Key-Id': env.key_id,
    'X-Envelope-Service-Id': env.service_id, 'X-Envelope-Ts': env.ts.isoformat(),
    'X-Envelope-Nonce': env.nonce, 'X-Envelope-Body-Sha256': env.body_sha256,
    'X-Envelope-Signature': env.signature, 'Idempotency-Key': env.nonce,
}
resp = httpx.post('https://yourusername--kairos-evolve-api-web.modal.run/v1/routing/events/batch',
                  json=body, headers=headers, timeout=10)
print(resp.status_code, resp.json())
"
```

Expected: `202 {'batch_id': '...', 'inserted': 0, 'policy_bumped': False, 'new_policy_version': None}`.

## Rollback

```bash
modal app rollback kairos-evolve-api
```
