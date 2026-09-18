variable "name" {
  description = "The project's name: realm.toml's [realm] name. It prefixes everything."
  type        = string
  validation {
    # The state bucket is <name>-tfstate-<account>: 63 characters at most.
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,40}$", var.name))
    error_message = "name: lowercase letters, digits and -, at most 41 characters."
  }
}

variable "region" {
  description = "The AWS region: realm.toml's [deploy] region."
  type        = string
}

variable "github_repository" {
  description = "owner/repo on GitHub: only its workflows can assume the roles."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository: owner/repo."
  }
}

variable "services" {
  description = "realm.toml's [[service]] names: an ECR repository <name>/<service> each."
  type        = list(string)
}

variable "budget_usd" {
  description = "The monthly budget, in USD. Alerts at 50%, 80% and 100% of it, and on a forecast over it."
  type        = number
  default     = 20
}

variable "budget_email" {
  description = "Where the budget's alerts go. Set TF_VAR_budget_email; never commit it."
  type        = string
  sensitive   = true
}

variable "create_oidc_provider" {
  description = "An account has one GitHub OIDC provider: false uses the one it already has."
  type        = bool
  default     = true
}
