# Dedicated RDS Postgres for the evolve-api (replaces Neon). Owns the
# kairos_evolve + kairos_audit schemas (provisioned by sql/init_schemas.sql).
resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds"
  description = "Allow Postgres from the App Runner VPC connector"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.apprunner_vpc.id]
  }
}

resource "aws_db_subnet_group" "evolve" {
  name       = "${local.name_prefix}-db"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "evolve" {
  name   = "${local.name_prefix}-pg16"
  family = "postgres16"

  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_instance" "evolve" {
  identifier                = "${local.name_prefix}-api"
  engine                    = "postgres"
  engine_version            = "16.3"
  instance_class            = var.db_instance_class
  allocated_storage         = var.db_allocated_storage_gb
  storage_type              = "gp3"
  storage_encrypted         = true
  username                  = "kairos_evolve"
  password                  = random_password.db.result
  db_name                   = "kairos_evolve"
  db_subnet_group_name      = aws_db_subnet_group.evolve.name
  vpc_security_group_ids    = [aws_security_group.rds.id]
  parameter_group_name      = aws_db_parameter_group.evolve.name
  publicly_accessible       = false
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-api-final"
  backup_retention_period   = 7
  deletion_protection       = false
}

# The DSN the evolve-api reads as KAIROS_EVOLVE_DATABASE_URL. Terraform sets
# the version from the RDS endpoint + the generated password (psycopg-compatible
# `postgresql://` scheme). `sslmode=require` because the instance is private but
# the connection still rides TLS.
resource "aws_secretsmanager_secret" "database_url" {
  name = "${local.secret_path}/database/url"
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql://kairos_evolve:%s@%s:5432/kairos_evolve?sslmode=require",
    random_password.db.result,
    aws_db_instance.evolve.address
  )
}
