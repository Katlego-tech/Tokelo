# Tokelo, one environment: everything in docs/design/infrastructure.md §6, a file per table.
# This file holds what the others share.
#
#   network.tf    the VPC, its four subnets, the route tables, the S3 gateway endpoint, fn and db
#   database.tf   Aurora PostgreSQL Serverless v2, pausing at 0 ACU
#
# The rest of §6 — the documents bucket, the events and queues, the functions, the user pool and
# the HTTP API — arrives with T019 and T020.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.64"
    }
  }
}

locals {
  prefix = "${var.name}-${var.environment}"
}

# Two zones, whichever two this region offers: Aurora needs a subnet group across two, and a
# function in one zone keeps running when the other is out.
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  zones = slice(data.aws_availability_zones.available.names, 0, 2)
}

data "aws_region" "current" {}
