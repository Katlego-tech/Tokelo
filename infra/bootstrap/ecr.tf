# The image archive (DESIGN.md §14.3): a repository <name>/<service> each. Tags never change, so a
# release's digest is fixed; only untagged images expire, since Lambda marks a function Failed
# when its image disappears.

resource "aws_ecr_repository" "service" {
  for_each             = toset(var.services)
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS" # the AWS-managed key: no monthly charge
  }
}

resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Untagged images, 14 days after they were pushed. Never a tag."
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 14
      }
      action = { type = "expire" }
    }]
  })
}

# Lambda pulls a function's image as itself: allow it, for this project's functions only.
resource "aws_ecr_repository_policy" "lambda" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name
  policy     = data.aws_iam_policy_document.lambda_pulls.json
}

data "aws_iam_policy_document" "lambda_pulls" {
  statement {
    sid     = "LambdaPullsThisProjectsImages"
    actions = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "aws:sourceArn"
      values   = ["arn:${local.partition}:lambda:${var.region}:${local.account}:function:${var.name}-*"]
    }
  }
}
