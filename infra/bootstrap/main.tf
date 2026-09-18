# The bootstrap (DESIGN.md §14.5): what the workflows need before they can run, applied once, by
# you, with scripts/realm/aws-bootstrap.sh. It starts with local state, then moves it into the
# bucket it creates here (backend.hcl, which the script writes).
#
#   state.tf   the state bucket and its KMS key
#   oidc.tf    GitHub's OIDC provider (or the account's existing one)
#   roles.tf   the four roles the workflows assume, and the permissions boundary
#   ecr.tf     a repository per service
#   budget.tf  the monthly budget and its alerts

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.64"
    }
  }
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = var.name
      Component = "bootstrap"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  account   = data.aws_caller_identity.current.account_id
  partition = data.aws_partition.current.partition
  # Everything the workflows touch is named <name>-..., and every IAM role Terraform creates
  # for the project lives under this path, with the boundary.
  iam_path = "/${var.name}/"
}
