resource "aws_security_group" "apprunner_vpc" {
  name        = "${local.name_prefix}-apprunner-vpc"
  description = "App Runner VPC connector egress"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_apprunner_vpc_connector" "evolve" {
  vpc_connector_name = "${local.name_prefix}-api-vpc"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.apprunner_vpc.id]
}

resource "aws_apprunner_auto_scaling_configuration_version" "evolve" {
  auto_scaling_configuration_name = "${local.name_prefix}-api"
  # Mirrors the Modal scaffold's posture: keep_warm=1 -> min_size=1,
  # concurrency_limit=10 -> max_concurrency=10. The evolve-api is a low-traffic
  # control-plane service (routing-event ingest, policy GET, the synchronous
  # candidate-return /v1/jobs/run); single-writer is fine.
  max_concurrency = 10
  min_size        = 1
  max_size        = 1
}

resource "aws_apprunner_service" "evolve" {
  service_name = "${local.name_prefix}-api"

  source_configuration {
    auto_deployments_enabled = false

    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_access.arn
    }

    image_repository {
      image_identifier      = "${aws_ecr_repository.api.repository_url}:${var.evolve_image_tag}"
      image_repository_type = "ECR"

      image_configuration {
        port = "8000"

        runtime_environment_variables = {
          KAIROS_EVOLVE_KEY_ID           = var.evolve_key_id
          KAIROS_GATEWAY_KEY_ID          = var.gateway_key_id
          KAIROS_EVOLVE_GATEWAY_BASE_URL = var.gateway_base_url
          KAIROS_GATEWAY_PUBLIC_KEY_HEX  = var.gateway_public_key_hex
          AWS_REGION                     = var.region
        }

        # KAIROS_EVOLVE_DATABASE_URL  -> the RDS DSN (rds.tf, set by terraform).
        # KAIROS_EVOLVE_PRIVATE_KEY_HEX -> K_evolve private half, injected
        # out-of-band (secrets.tf has no bootstrap version). Both are
        # whole-secret references (no JSON-field extraction).
        runtime_environment_secrets = {
          KAIROS_EVOLVE_DATABASE_URL    = aws_secretsmanager_secret.database_url.arn
          KAIROS_EVOLVE_PRIVATE_KEY_HEX = aws_secretsmanager_secret.evolve_private_key_hex.arn
        }
      }
    }
  }

  lifecycle {
    # CI rolls the image forward via `aws apprunner update-service`
    # (.github/workflows/deploy-aws.yml). Without ignore_changes, a later
    # `terraform apply` would revert the live image to var.evolve_image_tag
    # ("latest") and silently undo the most recent CI deploy. CI owns the
    # image tag; Terraform owns the rest of source_configuration.
    ignore_changes = [
      source_configuration[0].image_repository[0].image_identifier,
    ]
  }

  instance_configuration {
    cpu               = "0.5 vCPU"
    memory            = "1 GB"
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = aws_apprunner_vpc_connector.evolve.arn
    }
    ingress_configuration {
      is_publicly_accessible = true
    }
  }

  # /readyz does a SELECT 1 (DB-aware readiness) — stricter than /healthz
  # (liveness only), which matters because every evolve-api route needs the DB.
  health_check_configuration {
    protocol            = "HTTP"
    path                = "/readyz"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 3
  }

  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.evolve.arn
}
