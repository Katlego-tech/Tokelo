# The store (docs/design/infrastructure.md §6, "The tables"; ADR-0011).
#
# Two tables, and no server to place, patch or pause. Both are on-demand, so an environment
# nobody uses costs its stored bytes and nothing else, and neither has a secondary index: every
# access pattern in docs/design/domain-model.md §6 starts from a tenant's partition key.
#
# The keys are deliberately generic — pk and sk, both strings — because the item's type is part
# of its sort key (DOC#…, TIMELINE#…), which is what lets one query fetch a whole aggregate.

# Everything a tenant owns: pk = TENANT#<tenant id>, sk = the item's path under it.
# For Semgrep, the same reason as CKV_AWS_119 below: DynamoDB encrypts every table at rest with
# an AWS-owned key at no charge, and a customer key is USD 1 a month for control this project
# doesn't use (ADR-0011).
# nosemgrep: terraform.aws.security.aws-dynamodb-table-unencrypted.aws-dynamodb-table-unencrypted
resource "aws_dynamodb_table" "main" {
  #checkov:skip=CKV_AWS_119:the AWS-owned key encrypts it at no cost; a customer key is USD 1 a month for control this project doesn't use (ADR-0011)
  #checkov:skip=CKV_AWS_28:point-in-time recovery is charged per GB, so it is production's (var.protect); staging is made again from nothing
  name         = local.prefix
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.protect # charged per GB: production only
  }

  deletion_protection_enabled = var.protect
}

# The audit log: pk = SUBJECT#<pseudonym>, sk = <when>#<ulid>. It is a separate table because
# deleting an account deletes the tenant's partition, and the audit trail has to survive that
# (REQ-011, REQ-016). Nothing may change or delete an entry: that rule is in the functions'
# policies (T020), because DynamoDB has no table setting for it.
# nosemgrep: terraform.aws.security.aws-dynamodb-table-unencrypted.aws-dynamodb-table-unencrypted
resource "aws_dynamodb_table" "audit" {
  #checkov:skip=CKV_AWS_119:the AWS-owned key encrypts it at no cost; a customer key is USD 1 a month for control this project doesn't use (ADR-0011)
  #checkov:skip=CKV_AWS_28:point-in-time recovery is charged per GB, so it is production's (var.protect); staging is made again from nothing
  name         = "${local.prefix}-audit"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.protect
  }

  deletion_protection_enabled = var.protect
}
