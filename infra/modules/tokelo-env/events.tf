# The events and the queues (docs/design/infrastructure.md §6, "Events and queues"; ADR-0007).
#
# A stored object is a job. S3 tells EventBridge, a rule matches the key's shape, and the event
# lands on that job's queue, where the worker's event source mapping picks it up (T020). Nothing
# invokes a function directly, so a slow or failing worker holds the work in a queue instead of
# losing it.
#
# The queues are standard, not FIFO: order doesn't matter here, and every worker is idempotent
# (ADR-0007, and the conditional writes in domain-model.md §3). A message that fails three times
# goes to the queue's own dead-letter queue, where an alarm picks it up (alarms.tf).

locals {
  # One entry per job type: the keys it matches, and how long a worker may hold a message —
  # six times the function's timeout (§6's table), so a retry never overlaps a running job.
  queues = {
    lease = {
      patterns   = ["uploads/*/lease/*"]
      visibility = 720 # ocr, 120 s
    }
    page = {
      patterns   = ["jobs/page/*"]
      visibility = 720 # ocr, 120 s
    }
    evidence = {
      patterns   = ["uploads/*/photo/*", "uploads/*/notice/*", "uploads/*/chat/*"]
      visibility = 360 # evidence, 60 s
    }
    dossier = {
      patterns   = ["jobs/dossier/*"]
      visibility = 1800 # dossier, 300 s
    }
  }
}

resource "aws_sqs_queue" "dlq" {
  for_each = local.queues

  name                      = "${local.prefix}-${each.key}-dlq"
  message_retention_seconds = 1209600 # 14 days: long enough to look at a failure on Monday
  sqs_managed_sse_enabled   = true    # SQS's own key, at no charge

  # Only its own queue may send here.
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = ["arn:${data.aws_partition.current.partition}:sqs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:${local.prefix}-${each.key}"]
  })
}

resource "aws_sqs_queue" "job" {
  for_each = local.queues

  name                       = "${local.prefix}-${each.key}"
  message_retention_seconds  = 345600 # 4 days
  visibility_timeout_seconds = each.value.visibility
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = 3 # the third failure is the last (§4)
  })
}

# The rules. EventBridge's wildcard matching is what lets a tenant's ID sit in the middle of the
# key: uploads/<tenant>/lease/<document>.
resource "aws_cloudwatch_event_rule" "job" {
  for_each = local.queues

  name        = "${local.prefix}-${each.key}"
  description = "${local.prefix}: objects under ${join(", ", each.value.patterns)} become ${each.key} jobs"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.documents.id] }
      object = { key = [for pattern in each.value.patterns : { wildcard = pattern }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "job" {
  for_each = local.queues

  rule = aws_cloudwatch_event_rule.job[each.key].name
  arn  = aws_sqs_queue.job[each.key].arn
}

# Each queue takes messages from its own rule and from nothing else, so a message can't be forged
# onto a queue by anything that can call SQS.
resource "aws_sqs_queue_policy" "job" {
  for_each = local.queues

  queue_url = aws_sqs_queue.job[each.key].id
  policy    = data.aws_iam_policy_document.queue[each.key].json
}

data "aws_iam_policy_document" "queue" {
  for_each = local.queues

  statement {
    sid    = "OnlyItsOwnRule"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.job[each.key].arn]
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.job[each.key].arn]
    }
  }
}

data "aws_partition" "current" {}
