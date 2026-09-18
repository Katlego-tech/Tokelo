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
  description = "The [[service]] name in realm.toml: the container's name, and the ECR repository <name>/<service>."
  type        = string
}

variable "cluster_arn" {
  description = "The environment's ECS cluster, which envs/ creates and names <name>-<environment>."
  type        = string
}

variable "initial_image_tag" {
  description = "The release the service is created from: v0.0.0 (the seed) for staging, the first staged release for production. Afterwards the release pipeline chooses the image."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "The bootstrap's permissions_boundary output: every role under /<name>/ carries it."
  type        = string
}

variable "subnet_ids" {
  description = "The private subnets the tasks run in."
  type        = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "assign_public_ip" {
  description = "Only for tasks in a public subnet with no NAT: a cost choice for the project's network ADR."
  type        = bool
  default     = false
}

variable "cpu" {
  description = "Fargate CPU units: 256 is a quarter of a vCPU."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Fargate memory, MiB."
  type        = number
  default     = 512
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "port" {
  description = "The port a web service listens on (realm.toml's port); null for a worker."
  type        = number
  default     = null
}

variable "environment_variables" {
  description = "Plain settings. Secrets go in secrets."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Environment variable name => Secrets Manager secret or SSM parameter ARN. The execution role may read exactly these."
  type        = map(string)
  default     = {}
}

variable "task_role_arn" {
  description = "What the app itself may do in AWS: a role under /<name>/ named <name>-<environment>-..., with the boundary. null: nothing."
  type        = string
  default     = null
}

variable "read_only_root_filesystem" {
  description = "The container can't write to its image's files; mount a volume or use /tmp in memory if the app must."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "service_registry_arn" {
  description = "A Cloud Map service, for API Gateway's VPC link. null: none."
  type        = string
  default     = null
}

variable "target_group_arn" {
  description = "A load balancer's target group. null: none."
  type        = string
  default     = null
}
