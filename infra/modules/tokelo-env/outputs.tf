# What the environment's root, and later tasks, need to name these resources.

output "vpc_id" {
  description = "The environment's VPC."
  value       = aws_vpc.this.id
}

output "app_subnet_ids" {
  description = "The subnets the functions run in (T020)."
  value       = aws_subnet.app[*].id
}

output "function_security_group_id" {
  description = "The fn security group: out to the database and to S3 only."
  value       = aws_security_group.fn.id
}

output "database_cluster_arn" {
  description = "The Aurora cluster: what the Data API and the migrations address (ADR-0008)."
  value       = aws_rds_cluster.this.arn
}

output "database_endpoint" {
  description = "The writer's address, for the functions' connection string."
  value       = aws_rds_cluster.this.endpoint
}

output "database_name" {
  description = "The database inside the cluster."
  value       = aws_rds_cluster.this.database_name
}

output "database_master_secret_arn" {
  description = "The master user's secret, made and rotated by AWS. Only the migrations read it (ADR-0008)."
  value       = aws_rds_cluster.this.master_user_secret[0].secret_arn
}
