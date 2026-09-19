# The four roles GitHub's workflows assume (DESIGN.md §14.4), each trusting only its own kind of
# run, for at most two hours. They live at the root path, outside /<name>/, so the apply role,
# which may manage IAM only under /<name>/, can't change them or itself.
#
#   plan     pull requests       read everything but the project's data and secret values
#   apply    main                create and change the project's resources
#   release  v* tags             push images; deploy to <name>-staging-*
#   promote  main                read images; deploy to <name>-production-*

locals {
  # The repo's own subject prefix: GitHub's immutable form for newer repos (it names the owner's
  # and the repo's IDs, so a repo that later takes this one's name can't assume these roles).
  subject = var.github_subject_prefix != "" ? var.github_subject_prefix : "repo:${var.github_repository}"
  roles = {
    plan    = "${local.subject}:pull_request"
    apply   = "${local.subject}:ref:refs/heads/main"
    release = "${local.subject}:ref:refs/tags/v*"
    promote = "${local.subject}:ref:refs/heads/main"
  }
  arn        = "arn:${local.partition}"
  repos      = "${local.arn}:ecr:${var.region}:${local.account}:repository/${var.name}/*"
  project    = "${local.arn}:iam::${local.account}:role${local.iam_path}*"
  boundary   = "${local.arn}:iam::${local.account}:policy/${var.name}-boundary"
  state_objs = "${aws_s3_bucket.state.arn}/*"
}

data "aws_iam_policy_document" "trust" {
  for_each = local.roles
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = each.key == "release" ? "StringLike" : "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [each.value]
    }
  }
}

resource "aws_iam_role" "ci" {
  for_each             = local.roles
  name                 = "${var.name}-${each.key}"
  description          = "${var.name}: GitHub Actions, ${each.key} (DESIGN.md §14.4)"
  assume_role_policy   = data.aws_iam_policy_document.trust[each.key].json
  max_session_duration = 7200
}

# ------------------------------------------------------------------------- plan ---
resource "aws_iam_role_policy_attachment" "plan_reads" {
  role       = aws_iam_role.ci["plan"].name
  policy_arn = "${local.arn}:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "plan" {
  name   = "state-but-no-data"
  role   = aws_iam_role.ci["plan"].id
  policy = data.aws_iam_policy_document.plan.json
}

data "aws_iam_policy_document" "plan" {
  # A pull request can change the workflow that uses this role, so it reads the state (to plan)
  # and nothing else of value: no object in any other bucket, and no secret's value. (A
  # SecureString parameter is safe already: ReadOnlyAccess has no kms:Decrypt.)
  statement {
    sid       = "ReadTheState"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.state.arn]
  }
  statement {
    sid           = "NoOtherObjects"
    effect        = "Deny"
    actions       = ["s3:GetObject", "s3:GetObjectVersion"]
    not_resources = [local.state_objs]
  }
  statement {
    sid       = "NoSecretValues"
    effect    = "Deny"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["*"]
  }
}

# ------------------------------------------------------------------------ apply ---
resource "aws_iam_role_policy_attachment" "apply_services" {
  role = aws_iam_role.ci["apply"].name
  # Everything but IAM, Organizations and the account's settings. Creating an Organization would
  # move a free-plan account to the paid plan; this role can't.
  policy_arn = "${local.arn}:iam::aws:policy/PowerUserAccess"
}

resource "aws_iam_role_policy" "apply" {
  name   = "project-iam-and-guards"
  role   = aws_iam_role.ci["apply"].id
  policy = data.aws_iam_policy_document.apply.json
}

data "aws_iam_policy_document" "apply" {
  #checkov:skip=CKV_AWS_356:the "*" resources are IAM's read calls and service-linked roles only
  #checkov:skip=CKV_AWS_109:permissions changes are limited to /<name>/ and need the boundary
  statement {
    sid = "ProjectRolesCarryTheBoundary"
    actions = [
      "iam:CreateRole",
      "iam:PutRolePermissionsBoundary",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
    ]
    resources = [local.project]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary]
    }
  }
  statement {
    sid = "ProjectRoles"
    actions = [
      "iam:DeleteRole",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
      "iam:UpdateAssumeRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:PassRole",
    ]
    resources = [local.project]
  }
  statement {
    sid = "ProjectPolicies"
    actions = [
      "iam:CreatePolicy",
      "iam:DeletePolicy",
      "iam:CreatePolicyVersion",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
      "iam:TagPolicy",
      "iam:UntagPolicy",
    ]
    resources = ["${local.arn}:iam::${local.account}:policy${local.iam_path}*"]
  }
  statement {
    sid       = "ReadIAMAndServiceLinkedRoles"
    actions   = ["iam:Get*", "iam:List*", "iam:CreateServiceLinkedRole"]
    resources = ["*"]
  }
  statement {
    sid       = "KeepTheBoundary"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["*"]
  }
  # What the bootstrap made stays as it made it: the state, its key, and the image archive.
  statement {
    sid    = "KeepTheState"
    effect = "Deny"
    actions = [
      "s3:DeleteBucket",
      "s3:DeleteBucketPolicy",
      "s3:PutBucketPolicy",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
      "s3:PutLifecycleConfiguration",
      "s3:PutBucketPublicAccessBlock",
    ]
    resources = [aws_s3_bucket.state.arn]
  }
  statement {
    sid       = "KeepTheStateKey"
    effect    = "Deny"
    actions   = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:PutKeyPolicy", "kms:DeleteAlias"]
    resources = [aws_kms_key.state.arn, "${local.arn}:kms:${var.region}:${local.account}:alias/${var.name}-tfstate"]
  }
  statement {
    sid    = "KeepTheImages"
    effect = "Deny"
    actions = [
      "ecr:DeleteRepository",
      "ecr:BatchDeleteImage",
      "ecr:PutLifecyclePolicy",
      "ecr:DeleteLifecyclePolicy",
      "ecr:PutImageTagMutability",
      "ecr:SetRepositoryPolicy",
      "ecr:DeleteRepositoryPolicy",
    ]
    resources = [local.repos]
  }
}

# The most any role under /<name>/ may do, whatever policies it's given: no IAM, no
# Organizations or account settings, and never the Terraform state.
resource "aws_iam_policy" "boundary" {
  name        = "${var.name}-boundary"
  description = "${var.name}: the permissions boundary of every role Terraform creates (DESIGN.md §14.4)"
  policy      = data.aws_iam_policy_document.boundary.json
}

data "aws_iam_policy_document" "boundary" {
  #checkov:skip=CKV_AWS_107:a boundary caps other policies; it grants nothing on its own
  #checkov:skip=CKV_AWS_108:a boundary caps other policies; it grants nothing on its own
  #checkov:skip=CKV_AWS_109:a boundary caps other policies; it grants nothing on its own
  #checkov:skip=CKV_AWS_110:a boundary caps other policies; it grants nothing on its own
  #checkov:skip=CKV_AWS_111:a boundary caps other policies; it grants nothing on its own
  #checkov:skip=CKV_AWS_356:a boundary caps other policies; it grants nothing on its own
  statement {
    sid         = "AnythingButIAMAndTheAccount"
    not_actions = ["iam:*", "organizations:*", "account:*"]
    resources   = ["*"]
  }
  statement {
    sid     = "NeverTheState"
    effect  = "Deny"
    actions = ["s3:*", "kms:*"]
    resources = [
      aws_s3_bucket.state.arn,
      local.state_objs,
      aws_kms_key.state.arn,
    ]
  }
}

# ---------------------------------------------------------- release and promote ---
locals {
  deployers = {
    release = { env = "staging", push = true }
    promote = { env = "production", push = false }
  }
}

resource "aws_iam_role_policy" "deploy" {
  for_each = local.deployers
  name     = "deploy-${each.value.env}"
  role     = aws_iam_role.ci[each.key].id
  policy   = data.aws_iam_policy_document.deploy[each.key].json
}

data "aws_iam_policy_document" "deploy" {
  # What realm aws deploy|live|health and release.sh publish call (scripts/realm/aws.py).
  for_each = local.deployers
  statement {
    sid       = "SignInToECR"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "Images"
    actions = concat(
      ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:DescribeImages"],
      each.value.push ? [
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
      ] : [],
    )
    resources = [local.repos]
  }
  statement {
    sid     = "EcsServices"
    actions = ["ecs:DescribeServices", "ecs:UpdateService"]
    resources = [
      "${local.arn}:ecs:${var.region}:${local.account}:service/${var.name}-${each.value.env}/${var.name}-${each.value.env}-*",
    ]
  }
  statement {
    # Neither call can be limited to a family.
    sid       = "EcsTaskDefinitions"
    actions   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition"]
    resources = ["*"]
  }
  statement {
    sid       = "TagTheNewRevision"
    actions   = ["ecs:TagResource"]
    resources = ["${local.arn}:ecs:${var.region}:${local.account}:task-definition/${var.name}-${each.value.env}-*:*"]
    condition {
      test     = "StringEquals"
      variable = "ecs:CreateAction"
      values   = ["RegisterTaskDefinition"]
    }
  }
  statement {
    sid       = "PassTheTaskRoles"
    actions   = ["iam:PassRole"]
    resources = ["${local.arn}:iam::${local.account}:role${local.iam_path}${var.name}-${each.value.env}-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
  statement {
    sid = "LambdaFunctions"
    actions = [
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:UpdateFunctionCode",
      "lambda:PublishVersion",
      "lambda:GetAlias",
      "lambda:UpdateAlias",
      "lambda:InvokeFunction",
    ]
    resources = [
      "${local.arn}:lambda:${var.region}:${local.account}:function:${var.name}-${each.value.env}-*",
      "${local.arn}:lambda:${var.region}:${local.account}:function:${var.name}-${each.value.env}-*:*",
    ]
  }
}
