variable "region" {
  description = "AWS region for all resources (co-located with the gateway)"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Resource naming prefix (used in names and tags)"
  type        = string
  default     = "kairos-evolve"
}

variable "environment" {
  description = "Deployment environment (prod / staging)"
  type        = string
  default     = "prod"
}

variable "github_repo" {
  description = "GitHub repo in OWNER/REPO form for the OIDC trust policy (e.g. KairosPan/kairos-evolve)"
  type        = string
}

variable "evolve_image_tag" {
  description = "ECR image tag for kairos-evolve-api. Set after first push; CI rolls it forward."
  type        = string
  default     = "latest"
}

variable "db_instance_class" {
  description = "RDS instance class for the dedicated evolve Postgres"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 20
}

# ---- gateway <-> evolve handshake (non-secret config) ----

variable "gateway_base_url" {
  description = "The kairos gateway's App Runner HTTPS URL — where the evolve-api POSTs signed candidate/webhook callbacks (KAIROS_EVOLVE_GATEWAY_BASE_URL)."
  type        = string
}

variable "gateway_public_key_hex" {
  description = "The gateway's ed25519 PUBLIC key (hex) — the evolve-api verifies inbound gateway-signed envelopes against it (KAIROS_GATEWAY_PUBLIC_KEY_HEX). Public key, not a secret."
  type        = string
}

variable "gateway_key_id" {
  description = "The gateway's signing key id (KAIROS_GATEWAY_KEY_ID)."
  type        = string
  default     = "K_gw"
}

variable "evolve_key_id" {
  description = "The evolve-api's own signing key id (KAIROS_EVOLVE_KEY_ID)."
  type        = string
  default     = "K_evolve"
}
