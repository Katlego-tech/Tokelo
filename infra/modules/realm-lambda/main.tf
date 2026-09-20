# A container-image Lambda behind the alias live, which the release pipeline can deploy to
# (DESIGN.md §14.3, §14.5).
#
# - The names are the adapter's convention: function <name>-<env>-<service>, alias live, logs in
#   /aws/lambda/<name>-<env>-<service>.
# - It starts from initial_image_tag, by digest, and live points at that first version. After
#   that the pipeline chooses: it updates the code, publishes a version and moves live, so
#   Terraform ignores the image and the alias's version. A change made here (memory, variables)
#   applies to the unpublished code, and reaches live with the next release.
# - The handler must answer the event {"realm": "health"} with {"ok": true}: that's the release's
#   health check for a worker (docs/release/README.md).
# - x86_64 only, like the release's images.
# - /tmp is 512 MB unless ephemeral_storage_mb says otherwise: a worker that writes a file
#   while it works (an image, a PDF) sizes it here, and pays for it only while it runs.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.64"
    }
  }
}

locals {
  full_name = "${var.name}-${var.environment}-${var.service}"
}

data "aws_ecr_repository" "this" {
  name = "${var.name}/${var.service}"
}

data "aws_ecr_image" "initial" {
  repository_name = data.aws_ecr_repository.this.name
  image_tag       = var.initial_image_tag
}

# For Semgrep, the same reason as CKV_AWS_158 below: CloudWatch encrypts logs at rest already.
# nosemgrep: terraform.aws.security.aws-cloudwatch-log-group-unencrypted.aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "this" {
  #checkov:skip=CKV_AWS_338:30 days by default (DESIGN.md §14.9); a year of logs is a cost each project decides
  #checkov:skip=CKV_AWS_158:CloudWatch encrypts logs at rest already; a customer key costs a dollar a month each
  name              = "/aws/lambda/${local.full_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "this" {
  name                 = local.full_name
  path                 = "/${var.name}/"
  permissions_boundary = var.permissions_boundary_arn
  assume_role_policy   = data.aws_iam_policy_document.lambda.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "basics" {
  role = aws_iam_role.this.name
  policy_arn = (var.vpc == null
    ? "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  : "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole")
}

resource "aws_iam_role_policy_attachment" "more" {
  for_each   = toset(var.policy_arns)
  role       = aws_iam_role.this.name
  policy_arn = each.value
}

# For Semgrep, the same reason as CKV_AWS_50 below: traces go out by OpenTelemetry, not X-Ray.
# nosemgrep: terraform.aws.security.aws-lambda-x-ray-tracing-not-active.aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_50:traces go out by OpenTelemetry to the project's endpoint (DESIGN.md §9), not X-Ray
  #checkov:skip=CKV_AWS_116:a queue's own dead-letter queue catches what fails; asynchronous calls aren't used
  #checkov:skip=CKV_AWS_173:variables hold settings, not secrets; a customer key costs a dollar a month each
  #checkov:skip=CKV_AWS_272:code signing is for zip packages; this runs an image by digest, named in the signed release.json
  function_name                  = local.full_name
  role                           = aws_iam_role.this.arn
  package_type                   = "Image"
  image_uri                      = "${data.aws_ecr_repository.this.repository_url}@${data.aws_ecr_image.initial.image_digest}"
  architectures                  = ["x86_64"]
  memory_size                    = var.memory_size
  timeout                        = var.timeout
  reserved_concurrent_executions = var.reserved_concurrent_executions
  publish                        = true

  ephemeral_storage {
    size = var.ephemeral_storage_mb
  }

  dynamic "environment" {
    for_each = length(var.environment_variables) > 0 ? [var.environment_variables] : []
    content {
      variables = environment.value
    }
  }

  dynamic "vpc_config" {
    for_each = var.vpc == null ? [] : [var.vpc]
    content {
      subnet_ids         = vpc_config.value.subnet_ids
      security_group_ids = vpc_config.value.security_group_ids
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.this.name
  }

  lifecycle {
    ignore_changes = [image_uri] # the release pipeline's field (DESIGN.md §14.2)
  }
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.this.function_name
  function_version = aws_lambda_function.this.version
  lifecycle {
    ignore_changes = [function_version] # the release pipeline moves it
  }
}
