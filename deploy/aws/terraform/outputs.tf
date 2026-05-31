output "app_runner_service_url" {
  value       = "https://${aws_apprunner_service.evolve.service_url}"
  description = "Public HTTPS URL of the kairos-evolve-api. Set this as KAIROS_EVOLVE_API_BASE_URL on the gateway."
}

output "ecr_repository_url" {
  value       = aws_ecr_repository.api.repository_url
  description = "ECR repo URL for docker push"
}

output "ci_role_arn" {
  value       = aws_iam_role.ci_deploy.arn
  description = "Set as AWS_DEPLOY_ROLE_ARN in this repo's GitHub Actions secrets"
}

output "db_endpoint" {
  value       = aws_db_instance.evolve.address
  description = "RDS endpoint host (the full DSN lives in Secrets Manager at /kairos-evolve/<env>/database/url)"
}

output "service_arn" {
  value       = aws_apprunner_service.evolve.arn
  description = "App Runner service ARN (used by aws apprunner update-service)"
}

output "private_subnet_ids" {
  value       = aws_subnet.private[*].id
  description = "Private subnet IDs (for the RDS schema-bootstrap one-shot task)"
}
