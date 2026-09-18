variable "name" {
  description = "The project's name: realm.toml's [realm] name."
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

variable "service" {
  description = "The [[service]] name in realm.toml: the ECR repository <name>/<service>."
  type        = string
}

variable "initial_image_tag" {
  description = "The release the function is created from: v0.0.0 (the seed) for staging, the first staged release for production. Afterwards the release pipeline chooses the image."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "The bootstrap's permissions_boundary output: every role under /<name>/ carries it."
  type        = string
}

variable "memory_size" {
  description = "MB; the CPU grows with it."
  type        = number
  default     = 512
}

variable "timeout" {
  description = "Seconds. A queue's visibility timeout must be longer."
  type        = number
  default     = 30
}

variable "environment_variables" {
  type    = map(string)
  default = {}
}

variable "reserved_concurrent_executions" {
  description = "-1: no reservation. A new account's limit can be as low as 10, all of it unreserved."
  type        = number
  default     = -1
}

variable "vpc" {
  description = "Subnets and security groups, to reach a database in the VPC. null: outside the VPC."
  type = object({
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}

variable "policy_arns" {
  description = "Policies for what the function does (read a queue, write a bucket): created under /<name>/."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  type    = number
  default = 30
}
