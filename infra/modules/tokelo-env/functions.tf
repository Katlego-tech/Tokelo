# The four functions (docs/design/infrastructure.md §6, "The functions"; ADR-0002).
#
# Each one is the kit's realm-lambda module: a container image from ECR, behind the alias `live`,
# which is what the release pipeline moves. Terraform creates them from initial_image_tag and
# never chooses an image again.
#
# All four sit in the app subnets with the `fn` security group, so they have no route to the
# internet; they reach S3 and DynamoDB through the gateway endpoints (REQ-018). Each has its own
# role, and each role says exactly what that function does and nothing more.

data "aws_iam_policy" "boundary" {
  name = "${var.name}-boundary" # the bootstrap's: every project role carries it
}

locals {
  bucket = aws_s3_bucket.documents.arn

  # Every function reads and writes the tenants' table and appends to the audit log; the `api`
  # also tells the web app which user pool to sign in against (ADR-0010).
  common_environment = {
    TOKELO_TABLE            = aws_dynamodb_table.main.name
    TOKELO_AUDIT_TABLE      = aws_dynamodb_table.audit.name
    TOKELO_DOCUMENTS_BUCKET = aws_s3_bucket.documents.id
  }
}

# ------------------------------------------------------------------ api ---
module "api" {
  source                   = "../realm-lambda"
  name                     = var.name
  environment              = var.environment
  service                  = "api"
  initial_image_tag        = var.initial_image_tag
  permissions_boundary_arn = data.aws_iam_policy.boundary.arn

  memory_size          = 512
  timeout              = 29 # under the HTTP API's 30 s, so the caller sees the function's answer
  ephemeral_storage_mb = 512
  log_retention_days   = var.log_retention_days

  vpc = {
    subnet_ids         = aws_subnet.app[*].id
    security_group_ids = [aws_security_group.fn.id]
  }

  environment_variables = merge(local.common_environment, {
    TOKELO_USER_POOL_ID = aws_cognito_user_pool.tenants.id
    TOKELO_CLIENT_ID    = aws_cognito_user_pool_client.web.id
  })

  policy_arns = [aws_iam_policy.api.arn]
}

resource "aws_iam_policy" "api" {
  name        = "${local.prefix}-api"
  path        = "/${var.name}/"
  description = "${local.prefix}: what the api function may do (infrastructure.md §6)"
  policy      = data.aws_iam_policy_document.api.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "SignUploadsAndWriteDossierJobs"
    actions   = ["s3:PutObject"]
    resources = ["${local.bucket}/uploads/*", "${local.bucket}/jobs/dossier/*"]
  }
  statement {
    sid       = "ReadWhatTheTenantUploadedAndWhatWasBuilt"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${local.bucket}/uploads/*", "${local.bucket}/dossiers/*"]
  }
  # Account deletion (REQ-016, T048): every version of the tenant's files goes, and nothing else.
  statement {
    sid       = "DeleteTheTenantsFiles"
    actions   = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
    resources = ["${local.bucket}/uploads/*", "${local.bucket}/dossiers/*"]
  }
  statement {
    sid       = "ListTheVersionsToDelete"
    actions   = ["s3:ListBucketVersions", "s3:ListBucket"]
    resources = [local.bucket]
  }
  statement {
    sid = "TheTenantsItems"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:TransactWriteItems",
    ]
    resources = [aws_dynamodb_table.main.arn]
  }
  # Append and read. No UpdateItem, no DeleteItem: the audit log can't be edited (REQ-011).
  statement {
    sid       = "AppendToTheAuditLog"
    actions   = ["dynamodb:PutItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.audit.arn]
  }
}

# ------------------------------------------------------------- the workers ---
# Each worker reads its own queues, writes its own prefixes, and appends to the audit log.
locals {
  workers = {
    ocr = {
      memory    = 2048
      timeout   = 120
      ephemeral = 1024 # a page image while it is read
      queues    = ["lease", "page"]
    }
    evidence = {
      memory    = 512
      timeout   = 60
      ephemeral = 512
      queues    = ["evidence"]
    }
    dossier = {
      memory    = 1024
      timeout   = 300
      ephemeral = 2048 # the PDF it builds
      queues    = ["dossier"]
    }
  }

  # What each worker may reach in the bucket (infrastructure.md §6).
  worker_reads = {
    ocr      = ["${local.bucket}/uploads/*/lease/*", "${local.bucket}/jobs/page/*"]
    evidence = ["${local.bucket}/uploads/*"]
    dossier  = ["${local.bucket}/uploads/*", "${local.bucket}/jobs/dossier/*"]
  }
  worker_writes = {
    ocr      = ["${local.bucket}/jobs/page/*"]
    evidence = []
    dossier  = ["${local.bucket}/dossiers/*"]
  }
}

module "worker" {
  source   = "../realm-lambda"
  for_each = local.workers

  name                     = var.name
  environment              = var.environment
  service                  = each.key
  initial_image_tag        = var.initial_image_tag
  permissions_boundary_arn = data.aws_iam_policy.boundary.arn

  memory_size          = each.value.memory
  timeout              = each.value.timeout
  ephemeral_storage_mb = each.value.ephemeral
  log_retention_days   = var.log_retention_days

  vpc = {
    subnet_ids         = aws_subnet.app[*].id
    security_group_ids = [aws_security_group.fn.id]
  }

  environment_variables = local.common_environment
  policy_arns           = [aws_iam_policy.worker[each.key].arn]
}

resource "aws_iam_policy" "worker" {
  for_each = local.workers

  name        = "${local.prefix}-${each.key}"
  path        = "/${var.name}/"
  description = "${local.prefix}: what the ${each.key} worker may do (infrastructure.md §6)"
  policy      = data.aws_iam_policy_document.worker[each.key].json
}

data "aws_iam_policy_document" "worker" {
  for_each = local.workers

  statement {
    sid       = "ReadWhatItWorksOn"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = local.worker_reads[each.key]
  }

  dynamic "statement" {
    for_each = length(local.worker_writes[each.key]) > 0 ? [1] : []
    content {
      sid       = "WriteWhatItProduces"
      actions   = ["s3:PutObject"]
      resources = local.worker_writes[each.key]
    }
  }

  statement {
    sid       = "TheTenantsItems"
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.main.arn]
  }

  statement {
    sid       = "AppendToTheAuditLog"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.audit.arn]
  }

  statement {
    sid       = "ItsOwnQueues"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [for q in each.value.queues : aws_sqs_queue.job[q].arn]
  }
}

# One message at a time, failures reported per message, and at most two of each worker at once —
# the lowest AWS allows, which is what keeps the bill and the write rate small (§6).
resource "aws_lambda_event_source_mapping" "worker" {
  for_each = { for pair in flatten([
    for worker, settings in local.workers : [
      for queue in settings.queues : { key = "${worker}-${queue}", worker = worker, queue = queue }
    ]
  ]) : pair.key => pair }

  event_source_arn = aws_sqs_queue.job[each.value.queue].arn
  function_name    = module.worker[each.value.worker].alias_arn # live, never the function itself
  batch_size       = 1

  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 2
  }
}
