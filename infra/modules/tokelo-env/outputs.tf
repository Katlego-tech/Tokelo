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

output "documents_bucket" {
  description = "The documents bucket: uploads, job objects and dossiers (api.md §6's key layout)."
  value       = aws_s3_bucket.documents.id
}

output "documents_bucket_arn" {
  description = "The documents bucket, for the functions' policies (T020)."
  value       = aws_s3_bucket.documents.arn
}

output "queue_arns" {
  description = "Each job queue, for the functions' event source mappings (T020)."
  value       = { for name, queue in aws_sqs_queue.job : name => queue.arn }
}

output "alerts_topic_arn" {
  description = "Where the dead-letter alarms go. Subscribe an address to it by hand (alarms.tf)."
  value       = aws_sns_topic.alerts.arn
}

output "user_pool_id" {
  description = "The tenants' user pool; the web app reads it from /config.json (ADR-0010)."
  value       = aws_cognito_user_pool.tenants.id
}

output "user_pool_client_id" {
  description = "The web app's public client."
  value       = aws_cognito_user_pool_client.web.id
}

output "api_url" {
  description = "Where the web app and the JSON API answer: realm.toml's staging_url / production_url."
  value       = aws_apigatewayv2_api.http.api_endpoint
}
