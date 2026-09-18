output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_family" {
  value = aws_ecs_task_definition.this.family
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "log_group" {
  value = aws_cloudwatch_log_group.this.name
}
