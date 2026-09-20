# Tokelo, one environment: everything in docs/design/infrastructure.md §6, a file per table.
# This file holds what the others share.
#
#   network.tf    the VPC, its app subnets, the route tables, the two gateway endpoints and fn
#   tables.tf     the two DynamoDB tables (ADR-0011)
#   storage.tf    the documents bucket
#   events.tf     the EventBridge rules and the four queues, each with its dead-letter queue
#   identity.tf   the Cognito user pool and the web app's client
#   functions.tf  the four functions, their roles and their queue triggers
#   api.tf        the HTTP API, its authorizer and its routes
#   alarms.tf     the topic, and an alarm on each dead-letter queue
#
# §6's web app needs no resource of its own: the `api` function serves it from its image
# (ADR-0010).

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
