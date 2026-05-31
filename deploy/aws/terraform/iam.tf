# ---- App Runner ECR access role ----
resource "aws_iam_role" "apprunner_access" {
  name = "${local.name_prefix}-apprunner-access"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "build.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr_access" {
  role       = aws_iam_role.apprunner_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# ---- App Runner instance role (reads the evolve secrets) ----
resource "aws_iam_role" "apprunner_instance" {
  name = "${local.name_prefix}-apprunner-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "tasks.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Wildcard over the evolve secret subtree (/kairos-evolve/<env>/*) — covers the
# DB url + the private key + any future evolve secret without a policy update.
# Scoped to THIS service's namespace only (it cannot read the gateway's
# /kairos/<env>/* secrets).
resource "aws_iam_role_policy" "apprunner_instance_secrets" {
  name = "read-evolve-secrets"
  role = aws_iam_role.apprunner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:${local.secret_path}/*"
    }]
  })
}

# ---- GitHub Actions OIDC provider (DATA SOURCE — not a resource) ----
# The OIDC provider is an ACCOUNT-GLOBAL singleton keyed by URL; the gateway
# stack already creates `aws_iam_openid_connect_provider.github`. Creating it
# again here would fail with EntityAlreadyExists. Reference the existing one.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "ci_deploy" {
  name = "${local.name_prefix}-ci-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        # Narrow to this repo's main branch + numeric-semver release tags so a
        # non-release tag (e.g. `vmalicious`) can't bind a prod deploy.
        StringLike = {
          "token.actions.githubusercontent.com:sub" = [
            "repo:${var.github_repo}:ref:refs/heads/main",
            "repo:${var.github_repo}:ref:refs/tags/v[0-9]*",
          ]
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "ci_deploy" {
  name = "evolve-ci-deploy"
  role = aws_iam_role.ci_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = aws_ecr_repository.api.arn
      },
      {
        Effect   = "Allow"
        Action   = ["apprunner:ListServices"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "apprunner:DescribeService",
          "apprunner:StartDeployment",
          "apprunner:UpdateService"
        ]
        Resource = "arn:aws:apprunner:${var.region}:${data.aws_caller_identity.current.account_id}:service/${local.name_prefix}-api/*"
      },
      {
        # UpdateService re-asserts the full SourceConfiguration (incl. the
        # access/instance role ARNs), so AWS requires iam:PassRole on both
        # whenever a role ARN appears in the request — even unchanged.
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.apprunner_access.arn,
          aws_iam_role.apprunner_instance.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:DescribeSecret"]
        Resource = "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:${local.secret_path}/*"
      }
    ]
  })
}
