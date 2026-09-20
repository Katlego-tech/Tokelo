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
  description = "The fn security group: out to S3 and DynamoDB only."
  value       = aws_security_group.fn.id
}

output "table_name" {
  description = "The tenants' table: everything a tenant owns (ADR-0011)."
  value       = aws_dynamodb_table.main.name
}

output "table_arn" {
  description = "The tenants' table, for the functions' policies (T020)."
  value       = aws_dynamodb_table.main.arn
}

output "audit_table_name" {
  description = "The audit log's table, which nothing may change or delete (REQ-011)."
  value       = aws_dynamodb_table.audit.name
}

output "audit_table_arn" {
  description = "The audit log's table, for the functions' policies (T020)."
  value       = aws_dynamodb_table.audit.arn
}
