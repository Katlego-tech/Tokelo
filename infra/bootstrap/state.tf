# The Terraform state of every root (bootstrap, envs/*), one object each, in one bucket:
# versioned, encrypted with its own key, private, TLS only, old versions kept 90 days. Terraform
# locks with S3's own lock file (use_lockfile), so there's no DynamoDB table.

resource "aws_kms_key" "state" {
  description             = "${var.name}: Terraform state"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.state_key.json
  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "state_key" {
  # A key policy's resource is always "*", meaning this key; IAM policies decide who else may use it.
  #checkov:skip=CKV_AWS_109:a key policy's "*" resource is the key itself; the account's IAM policies narrow it
  #checkov:skip=CKV_AWS_111:a key policy's "*" resource is the key itself; the account's IAM policies narrow it
  #checkov:skip=CKV_AWS_356:a key policy's "*" resource is the key itself; the account's IAM policies narrow it
  statement {
    sid       = "TheAccountAdministersTheKey"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account}:root"]
    }
  }
}

resource "aws_kms_alias" "state" {
  name          = "alias/${var.name}-tfstate"
  target_key_id = aws_kms_key.state.key_id
}

resource "aws_s3_bucket" "state" {
  #checkov:skip=CKV_AWS_18:access logging needs a second bucket; CloudTrail records who read the state
  #checkov:skip=CKV_AWS_144:one region is enough: every version of the state is kept for 90 days
  #checkov:skip=CKV2_AWS_62:nothing reacts to state changes, so there's nothing to notify
  bucket = "${var.name}-tfstate-${local.account}"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state_bucket.json
}

data "aws_iam_policy_document" "state_bucket" {
  statement {
    sid     = "TLSOnly"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
