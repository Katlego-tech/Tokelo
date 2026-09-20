# One Tokelo environment. Staging and production call this module with different values, so
# they can't drift apart (docs/design/infrastructure.md §7, §8).

variable "name" {
  description = "The project's name: realm.toml's [realm] name. Every resource is <name>-<environment>-…"
  type        = string
}

variable "environment" {
  description = "staging or production."
  type        = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment: staging or production."
  }
}

variable "vpc_cidr" {
  description = "The VPC's range: 10.20.0.0/16 in staging, 10.21.0.0/16 in production (§6)."
  type        = string
}

variable "app_subnet_cidrs" {
  description = "Two /24s, one per availability zone, for the functions."
  type        = list(string)
  validation {
    condition     = length(var.app_subnet_cidrs) == 2
    error_message = "app_subnet_cidrs: two subnets, because Aurora and Lambda both need two zones."
  }
}

variable "db_subnet_cidrs" {
  description = "Two /24s the database alone sits in."
  type        = list(string)
  validation {
    condition     = length(var.db_subnet_cidrs) == 2
    error_message = "db_subnet_cidrs: two subnets, because Aurora needs two zones."
  }
}

variable "database_engine_version" {
  description = "Aurora PostgreSQL 16.x: at least 16.3, which is what capacity 0 (pausing) needs. Checked with `aws rds describe-db-engine-versions --engine aurora-postgresql` when it changes."
  type        = string
  default     = "16.14"
  validation {
    condition     = can(regex("^16\\.(3|[4-9]|[1-9][0-9]+)$", var.database_engine_version))
    error_message = "database_engine_version: 16.3 or newer, the versions that pause at 0 ACU."
  }
}

variable "database_max_capacity" {
  description = "Aurora capacity units. The minimum is always 0: the database pauses when idle (ADR-0004)."
  type        = number
  default     = 2
}

variable "protect" {
  description = "Production: deletion protection on, and a final snapshot when something is destroyed. Staging is disposable, so both are off there (§6)."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "How long CloudWatch keeps this environment's logs (§6)."
  type        = number
  default     = 30
}
