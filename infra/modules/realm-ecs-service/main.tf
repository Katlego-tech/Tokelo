# An ECS service on Fargate that the release pipeline can deploy to (DESIGN.md §14.3, §14.5).
#
# - The names are the adapter's convention: service and task family <name>-<env>-<service>, the
#   container <service>, logs in /ecs/<name>-<env>-<service>.
# - It starts from initial_image_tag, by digest. After that the pipeline chooses the image: it
#   registers a copy of the family's latest revision with only the image changed, so Terraform
#   ignores the service's task_definition, and a change made here (CPU, variables) goes out with
#   the next release.
# - ECS's circuit breaker rolls a failed deployment back, and the adapter reports it.
# - x86_64 only, like the release's images.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.64"
    }
  }
}

data "aws_region" "current" {}

locals {
  full_name = "${var.name}-${var.environment}-${var.service}"
  port      = var.port == null ? {} : { PORT = tostring(var.port) } # as on the other platforms
}

data "aws_ecr_repository" "this" {
  name = "${var.name}/${var.service}"
}

data "aws_ecr_image" "initial" {
  repository_name = data.aws_ecr_repository.this.name
  image_tag       = var.initial_image_tag
}

resource "aws_cloudwatch_log_group" "this" {
  #checkov:skip=CKV_AWS_338:30 days by default (DESIGN.md §14.9); a year of logs is a cost each project decides
  #checkov:skip=CKV_AWS_158:CloudWatch encrypts logs at rest already; a customer key costs a dollar a month each
  name              = "/ecs/${local.full_name}"
  retention_in_days = var.log_retention_days
}

# Pulling the image, writing the logs, and reading exactly the secrets named in var.secrets.
resource "aws_iam_role" "execution" {
  name                 = "${local.full_name}-execution"
  path                 = "/${var.name}/"
  permissions_boundary = var.permissions_boundary_arn
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks.json
}

data "aws_iam_policy_document" "ecs_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "secrets" {
  count  = length(var.secrets) > 0 ? 1 : 0
  name   = "read-its-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.secrets[0].json
}

data "aws_iam_policy_document" "secrets" {
  count = length(var.secrets) > 0 ? 1 : 0
  statement {
    actions   = ["secretsmanager:GetSecretValue", "ssm:GetParameters"]
    resources = values(var.secrets)
  }
}

resource "aws_ecs_task_definition" "this" {
  family                   = local.full_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = var.task_role_arn
  skip_destroy             = true # the pipeline's revisions are copies of this one; keep them usable

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name                   = var.service
    image                  = "${data.aws_ecr_repository.this.repository_url}@${data.aws_ecr_image.initial.image_digest}"
    essential              = true
    readonlyRootFilesystem = var.read_only_root_filesystem
    portMappings           = var.port == null ? [] : [{ containerPort = var.port, protocol = "tcp" }]
    environment = [
      for key, value in merge(var.environment_variables, local.port) : { name = key, value = value }
    ]
    secrets = [for key in sort(keys(var.secrets)) : { name = key, valueFrom = var.secrets[key] }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this.name
        awslogs-region        = data.aws_region.current.region
        awslogs-stream-prefix = var.service
      }
    }
  }])
}

resource "aws_ecs_service" "this" {
  name            = local.full_name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = var.assign_public_ip
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  dynamic "service_registries" {
    for_each = var.service_registry_arn == null ? [] : [var.service_registry_arn]
    content {
      registry_arn = service_registries.value
    }
  }

  dynamic "load_balancer" {
    for_each = var.target_group_arn == null ? [] : [var.target_group_arn]
    content {
      target_group_arn = load_balancer.value
      container_name   = var.service
      container_port   = var.port
    }
  }

  lifecycle {
    # The release pipeline's field: which revision runs (DESIGN.md §14.2).
    ignore_changes = [task_definition]
  }
}
