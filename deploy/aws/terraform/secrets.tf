resource "random_password" "db" {
  length = 32
  # `special = true` to match the gateway's provisioned posture. Changing this
  # later forces a password regen + secret-version replacement, locking App
  # Runner out of RDS until the env cache cycles — leave aligned.
  special = true
}

# The evolve-api's OWN ed25519 signing key (K_evolve private half). Whole-secret
# reference — NO bootstrap version here; injected out-of-band via
# `aws secretsmanager put-secret-value` (see deploy/aws/README.md). The matching
# PUBLIC half is registered into the GATEWAY's existing
# /kairos/prod/evolve/public_key_hex secret so the gateway can verify the
# evolve-api's signed candidate/webhook callbacks.
resource "aws_secretsmanager_secret" "evolve_private_key_hex" {
  name = "${local.secret_path}/evolve/private_key_hex"
}
