output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "alias_arn" {
  description = "live's ARN: point event-source mappings (an SQS queue) here, never at the function."
  value       = aws_lambda_alias.live.arn
}

output "role_name" {
  value = aws_iam_role.this.name
}

output "log_group" {
  value = aws_cloudwatch_log_group.this.name
}
