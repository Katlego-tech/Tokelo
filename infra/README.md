# infra/: the aws platform's Terraform

Secret Realm's AWS platform (DESIGN.md §14.5). The gate checks everything here: format, validity,
a committed lock file per root, tflint and checkov (§14.6).

| Folder | What | Applied by |
|---|---|---|
| `bootstrap/` | the state bucket and its key, GitHub's OIDC provider, the four roles and the permissions boundary, a repository per service, the budget | you, with `scripts/realm/aws-bootstrap.sh` |
| `modules/realm-ecs-service/` | an ECS service on Fargate the release can deploy to | — |
| `modules/realm-lambda/` | a container-image Lambda behind the alias `live` | — |
| `envs/staging/`, `envs/production/` | the project's architecture, from its C4 containers diagram | realm-infra: staging on merge, production by hand |

## The rules the modules keep, and yours must too

- **Names:** the ECS cluster is `<name>-<env>`; services, task families and functions are
  `<name>-<env>-<service>`; the container is `<service>`; the Lambda alias is `live`. The release
  finds everything by these names, and the release and promote roles may touch only
  `<name>-staging-*` and `<name>-production-*`.
- **IAM:** every role you create is under the path `/<name>/`, carries the bootstrap's
  permissions boundary, and is named `<name>-<env>-…`. The apply role can create no other kind.
- **Images:** Terraform creates each service from `initial_image_tag`; after that only the
  release chooses the image, so Terraform ignores the fields it sets (DESIGN.md §14.2).
- **Secrets:** never as Terraform values, which would put them in the state. Use
  `manage_master_user_password = true` for RDS, and create secrets' values outside Terraform.

## A staging environment, for example

```hcl
data "aws_iam_policy" "boundary" {
  name = "${var.name}-boundary"
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name}-staging"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

module "api" {
  source                   = "../../modules/realm-ecs-service"
  name                     = var.name
  environment              = "staging"
  service                  = "api"
  cluster_arn              = aws_ecs_cluster.this.arn
  initial_image_tag        = "v0.0.0"
  permissions_boundary_arn = data.aws_iam_policy.boundary.arn
  port                     = 8000
  subnet_ids               = aws_subnet.private[*].id
  security_group_ids       = [aws_security_group.api.id]
}

module "ocr" {
  source                   = "../../modules/realm-lambda"
  name                     = var.name
  environment              = "staging"
  service                  = "ocr"
  initial_image_tag        = "v0.0.0"
  permissions_boundary_arn = data.aws_iam_policy.boundary.arn
  timeout                  = 120
  policy_arns              = [aws_iam_policy.ocr.arn]
}

resource "aws_lambda_event_source_mapping" "ocr" {
  event_source_arn = aws_sqs_queue.ocr.arn
  function_name    = module.ocr.alias_arn # live, never the function itself
}
```

Production is the same, with `environment = "production"` and `initial_image_tag` set to the
first release that passed staging.
