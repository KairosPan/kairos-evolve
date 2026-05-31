terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state in S3 with native S3 lockfiles (use_lockfile = true).
  # Reuses the SAME bucket the gateway provisioned (out-of-band via the
  # gateway repo's migrate-to-s3-backend.sh) with a DISTINCT key, so the
  # evolve-api stack has its own independent state object. If the bucket
  # name differs in your account, override it here before `terraform init`.
  backend "s3" {
    bucket       = "kairos-terraform-state-430102461165"
    key          = "aws/evolve/prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  secret_path = "/${var.project_name}/${var.environment}"
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
}
