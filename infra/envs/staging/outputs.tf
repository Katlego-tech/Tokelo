# What the next tasks and the inspections (T051) read from the state.

output "vpc_id" {
  description = "Staging's VPC."
  value       = module.env.vpc_id
}

output "database_cluster_arn" {
  description = "Staging's Aurora cluster: the migrations address it through the Data API (ADR-0008)."
  value       = module.env.database_cluster_arn
}

output "database_master_secret_arn" {
  description = "Staging's master-user secret, made and rotated by AWS."
  value       = module.env.database_master_secret_arn
}
