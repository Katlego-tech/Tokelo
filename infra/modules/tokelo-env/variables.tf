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

variable "protect" {
  description = "Production: deletion protection and point-in-time recovery on the tables. Staging is disposable, so both are off there (§6)."
  type        = bool
  default     = false
}
