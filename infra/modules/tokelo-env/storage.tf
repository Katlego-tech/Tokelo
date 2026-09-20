# The documents bucket (docs/design/infrastructure.md §6, "The documents bucket").
#
# Everything a tenant uploads, every job object the workers write to each other, and every
# dossier the `dossier` function builds. Nothing here is public, nothing is served from here —
# the web app comes out of the `api` image (ADR-0010) — and every object arrives through a
# pre-signed POST the `api` signs, never through the API itself (REQ-002).
#
# The key layout is api.md §6: uploads/<tenant>/<kind>/<document>, jobs/page/…,
# jobs/dossier/…, dossiers/… . events.tf turns those prefixes into queues.

resource "aws_s3_bucket" "documents" {
  #checkov:skip=CKV_AWS_144:replication would copy tenants' documents into a second region and double their storage; one region is the decision (ADR-0001, ADR-0003)
  #checkov:skip=CKV_AWS_18:server access logs need a second bucket that is paid for by the GB, for a bucket only the functions' roles can reach; what happened to a document is in the audit log (REQ-011)
  bucket = "${local.prefix}-documents-${data.aws_caller_identity.current.account_id}"

  # Staging is meant to be destroyed and made again; production keeps what it holds.
  force_destroy = !var.protect
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# No ACLs at all: the bucket owner owns every object, and access is the bucket policy's and the
# roles' to decide.
resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms" # the AWS-managed aws/s3 key: no customer key at USD 1 a month
      kms_master_key_id = "alias/aws/s3"
    }
    # One key call per upload instead of one per object: the difference between cents and dollars.
    bucket_key_enabled = true
  }
}

# Versioning is half of the tamper-evidence: the digest says a file changed, the old version
# proves what it was (REQ-008, REQ-010).
resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket     = aws_s3_bucket.documents.id
  depends_on = [aws_s3_bucket_versioning.documents]

  # A job object is a message between two functions; a week is long enough to look at one.
  rule {
    id     = "expire-job-objects"
    status = "Enabled"
    filter {
      prefix = "jobs/"
    }
    expiration {
      days = 7
    }
  }

  # Uploads and dossiers stay until the tenant deletes them (T048). Only superseded versions age
  # out, and an upload that never finished is not paid for.
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Plain HTTP can't reach an object even with a signed URL.
resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.documents.id
  policy = data.aws_iam_policy_document.documents.json
}

data "aws_iam_policy_document" "documents" {
  statement {
    sid    = "DenyWithoutTLS"
    effect = "Deny"
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# How a stored object becomes a job: S3 tells EventBridge, and events.tf's rules do the rest
# (ADR-0007). There is no Lambda notification here, so no function is invoked by S3 directly.
resource "aws_s3_bucket_notification" "documents" {
  bucket      = aws_s3_bucket.documents.id
  eventbridge = true
}

data "aws_caller_identity" "current" {}
