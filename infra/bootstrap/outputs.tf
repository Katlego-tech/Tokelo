# aws-bootstrap.sh reads these: the registry goes into realm.toml, the roles into the
# repository's variables, and the bucket and key into each root's backend.hcl.

output "registry" {
  description = "realm.toml's [deploy] registry: the images are <registry>/<service>."
  value       = "${local.account}.dkr.ecr.${var.region}.amazonaws.com/${var.name}"
}

output "region" {
  value = var.region
}

output "roles" {
  description = "The workflows' roles: AWS_PLAN_ROLE, AWS_APPLY_ROLE, AWS_RELEASE_ROLE, AWS_PROMOTE_ROLE."
  value       = { for kind, role in aws_iam_role.ci : kind => role.arn }
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "state_key" {
  value = aws_kms_key.state.arn
}

output "permissions_boundary" {
  description = "Every role under /<name>/ carries it: the modules' permissions_boundary_arn."
  value       = aws_iam_policy.boundary.arn
}
