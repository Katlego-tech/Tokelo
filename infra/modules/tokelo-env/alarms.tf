# The alarms (docs/design/infrastructure.md §6, "Alarms").
#
# One topic per environment, and one alarm per dead-letter queue: a job that failed three times
# is work a tenant is waiting for, so the operator hears about it rather than finding it later.
#
# The topic has no subscription here. An address is a person, not infrastructure, and this is a
# public repository (the budget's email is passed the same way, at bootstrap). Katlego subscribes
# once per environment and confirms by email:
#
#   aws sns subscribe --topic-arn <the alerts_topic_arn output> \
#     --protocol email --notification-endpoint <address> --profile tokelo

resource "aws_sns_topic" "alerts" {
  name              = "${local.prefix}-alerts"
  kms_master_key_id = "alias/aws/sns" # AWS's own SNS key, at no charge
}

resource "aws_cloudwatch_metric_alarm" "dead_letter" {
  for_each = local.queues

  alarm_name        = "${local.prefix}-${each.key}-dead-letter"
  alarm_description = "${local.prefix}: a ${each.key} job failed three times and is in the dead-letter queue"

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  dimensions  = { QueueName = aws_sqs_queue.dlq[each.key].name }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching" # an empty queue reports nothing, which is the good case

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}
