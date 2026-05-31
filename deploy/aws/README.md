# kairos-evolve-api — AWS App Runner deploy

Primary (and only) production path. Mirrors the kairos gateway's App Runner
stack (`deploy/aws/` in the kairos repo): **App Runner** for the FastAPI service
+ a **dedicated RDS Postgres** + **Secrets Manager**, region **us-east-1**.
(The old Modal scaffold was removed — see the kairos repo's
`docs/superpowers/specs/2026-05-31-kairos-evolve-api-aws-migration.md`.)

> The future long-GEPA worker (minutes-to-hours, off the HTTP request path) is a
> **separate** ECS-Fargate/Batch service — NOT this App Runner service and NOT
> built yet (#35). App Runner hosts the synchronous request/response evolve-api
> (routing ingest, policy GET, the candidate-return `/v1/jobs/run`).

Terraform: `deploy/aws/terraform/` (validated with `terraform validate`). The
Docker image is built from the repo-root `Dockerfile` (validated with
`docker build`). State lives in the gateway's S3 bucket under a distinct key
(`aws/evolve/prod/terraform.tfstate`).

## Prerequisites
- AWS account (the same one as the gateway — the GitHub OIDC provider is reused
  via a data source, not re-created).
- `terraform >= 1.6`, `aws` CLI, `docker`.
- `terraform.tfvars` filled in from `terraform.tfvars.example` (`github_repo`,
  `gateway_base_url`, `gateway_public_key_hex`).

## Bootstrap (first deploy)
App Runner's `CreateService` validates the image exists in ECR, so the ECR repo
+ a first image must exist before the App Runner resource applies.

```bash
cd deploy/aws/terraform
terraform init

# 1. Create just the ECR repo first.
terraform apply -target=aws_ecr_repository.api -target=aws_ecr_lifecycle_policy.api

# 2. Build + push the first image (clean context; --provenance=false to match
#    the gateway's build hygiene).
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
docker build --provenance=false -t $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/kairos-evolve-api:latest ..  # build from repo root
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/kairos-evolve-api:latest

# 3. Apply the rest (VPC, RDS, App Runner, IAM, secrets).
terraform apply
```

## Secrets
- `KAIROS_EVOLVE_DATABASE_URL` (`/kairos-evolve/prod/database/url`) — **set by
  Terraform** from the RDS endpoint + generated password (it has a
  `secret_version`). No manual step.
- `KAIROS_EVOLVE_PRIVATE_KEY_HEX` (`/kairos-evolve/prod/evolve/private_key_hex`)
  — **inject out-of-band** (Terraform declares the secret with no version):
  ```bash
  # generate K_evolve (ed25519) — keep the private hex secret, note the public hex
  python3 - <<'PY'
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
  from cryptography.hazmat.primitives import serialization as s
  k = Ed25519PrivateKey.generate()
  priv = k.private_bytes(s.Encoding.Raw, s.PrivateFormat.Raw, s.NoEncryption()).hex()
  pub  = k.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw).hex()
  print("PRIVATE:", priv); print("PUBLIC :", pub)
  PY
  aws secretsmanager put-secret-value \
    --secret-id /kairos-evolve/prod/evolve/private_key_hex \
    --secret-string '<PRIVATE hex>'
  ```

## RDS schema bootstrap (fresh instance)
The instance starts with an empty `kairos_evolve` database. Apply the schema +
tables once (the instance is private — run from a one-shot bastion / SSM
port-forward into the private subnets, the same way the gateway runs migrations):
```bash
psql "$KAIROS_EVOLVE_DATABASE_URL" -f ../../../sql/init_schemas.sql
```

## gateway ↔ evolve key registration (the cross-service handshake)
1. Push **K_evolve's PUBLIC half** into the GATEWAY's existing secret so the
   gateway can verify the evolve-api's signed candidate/webhook callbacks:
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id /kairos/prod/evolve/public_key_hex --secret-string '<PUBLIC hex>'
   ```
   (The gateway already wires this secret into its App Runner env as
   `KAIROS_EVOLVE_PUBLIC_KEY_HEX` — see the gateway's `apprunner.tf`.)
2. Set `gateway_public_key_hex` (the gateway's own public key) + `gateway_base_url`
   in `terraform.tfvars` so the evolve-api can verify inbound gateway envelopes
   and POST callbacks back.
3. After `terraform apply`, set the gateway's `KAIROS_EVOLVE_API_BASE_URL` to the
   evolve App Runner URL (`terraform output app_runner_service_url`).

## CI
`.github/workflows/deploy-aws.yml` (OIDC, no long-lived keys): on a `v*` tag it
builds + pushes `:GIT_SHA` to ECR and rolls the App Runner service via
`aws apprunner update-service` (merging only the image, preserving the env/secret
config), then polls `/readyz`. Set the repo secret `AWS_DEPLOY_ROLE_ARN` to
`terraform output ci_role_arn`. The OIDC trust is narrowed to this repo's `main`
+ numeric-semver tags.

## Verify
```bash
curl https://$(terraform output -raw app_runner_service_url | sed 's#https://##')/readyz
# -> {"status":"ok","db":"ok"}
```

## Flag posture
The self-evolution loop is **inert** until the gateway sets `KAIROS_EVOLVE_REMOTE=1`
(default OFF) — so standing up this service does not change gateway behavior until
that flip + the key registration above are both done.
