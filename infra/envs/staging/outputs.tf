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
