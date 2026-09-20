# The database (docs/design/infrastructure.md §6, "The database"; ADR-0004, ADR-0008).
#
# Aurora PostgreSQL Serverless v2 scaling from 0 ACU: after ten idle minutes it pauses and only
# its storage is charged, which is what makes a database affordable on the free plan. It is in
# the DB subnets, reachable only from the fn security group, and it has no route to the internet.
#
# Nothing here holds a password. The master user's is AWS's to make and to keep
# (manage_master_user_password), and the migrations reach the database through the Data API from
# CI, which is outside the VPC (ADR-0008). The functions sign in as the application user with
# their IAM role, so there is no application password anywhere either.

resource "aws_db_subnet_group" "this" {
  name        = local.prefix
  description = "${local.prefix}: the database's own subnets, in two zones"
  subnet_ids  = aws_subnet.db[*].id
}

resource "aws_rds_cluster" "this" {
  #checkov:skip=CKV_AWS_139:deletion protection is production's (var.protect); staging is meant to be thrown away and made again
  #checkov:skip=CKV_AWS_327:the AWS-managed aws/rds key encrypts it; a customer key is USD 1 a month for control this project doesn't use (§8, ADR-0003)
  #checkov:skip=CKV2_AWS_27:query logging writes every statement, and the tenants' data with it, into CloudWatch (§Threats); the errors in the postgresql log are what this project reads
  #checkov:skip=CKV2_AWS_8:a backup plan duplicates the automated backups below, and costs more than this database holds
  cluster_identifier = local.prefix
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned" # what Serverless v2 runs as
  engine_version     = var.database_engine_version
  database_name      = var.name
  port               = 5432

  # 0 to var.database_max_capacity ACU: at 0 the database is paused (ADR-0004).
  serverlessv2_scaling_configuration {
    min_capacity             = 0
    max_capacity             = var.database_max_capacity
    seconds_until_auto_pause = 600
  }

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]

  master_username             = "${var.name}_admin"
  manage_master_user_password = true

  iam_database_authentication_enabled = true # how the functions sign in (ADR-0008)
  enable_http_endpoint                = true # the Data API, which the migrations use

  storage_encrypted               = true # with the AWS-managed aws/rds key
  backup_retention_period         = 1
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = ["postgresql"]

  deletion_protection       = var.protect
  skip_final_snapshot       = !var.protect
  final_snapshot_identifier = var.protect ? "${local.prefix}-final" : null

  depends_on = [aws_cloudwatch_log_group.database]
}

resource "aws_rds_cluster_instance" "this" {
  #checkov:skip=CKV_AWS_118:Enhanced Monitoring is charged per instance per month, for metrics this project doesn't act on (§6)
  #checkov:skip=CKV_AWS_353:Performance Insights beyond its free week is charged per ACU, and a paused database has none (§6)
  identifier         = "${local.prefix}-1"
  cluster_identifier = aws_rds_cluster.this.id
  engine             = aws_rds_cluster.this.engine
  engine_version     = aws_rds_cluster.this.engine_version
  instance_class     = "db.serverless"

  # One writer, no reader: a second instance would double the bill for an availability this
  # project doesn't promise. Aurora still keeps the data in both zones.
  publicly_accessible          = false
  performance_insights_enabled = false # USD 0 only for 7 days of it, and unused here
  monitoring_interval          = 0     # Enhanced Monitoring is charged per instance
  auto_minor_version_upgrade   = true
}

# Aurora would otherwise make this log group itself and keep it forever.
# nosemgrep: terraform.aws.security.aws-cloudwatch-log-group-unencrypted.aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "database" {
  #checkov:skip=CKV_AWS_338:30 days is this project's retention everywhere (§6); a year of logs is a cost the budget doesn't carry
  #checkov:skip=CKV_AWS_158:CloudWatch encrypts logs at rest already; a customer key is USD 1 a month for control this project doesn't use
  name              = "/aws/rds/cluster/${local.prefix}/postgresql"
  retention_in_days = var.log_retention_days
}
