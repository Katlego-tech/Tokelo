# What the next tasks and the inspections (T051) read from the state.

output "vpc_id" {
  description = "Staging's VPC."
  value       = module.env.vpc_id
}

output "table_name" {
  description = "Staging's tenants' table (ADR-0011)."
  value       = module.env.table_name
}

output "audit_table_name" {
  description = "Staging's audit table."
  value       = module.env.audit_table_name
}

output "api_url" {
  description = "Where staging answers: realm.toml's staging_url."
  value       = module.env.api_url
}

output "user_pool_id" {
  description = "Staging's user pool; /config.json hands it to the web app."
  value       = module.env.user_pool_id
}

output "user_pool_client_id" {
  description = "The web app's public client."
  value       = module.env.user_pool_client_id
}
