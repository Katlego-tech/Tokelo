# Production: the project's own architecture, from its C4 containers diagram
# (DESIGN.md §14.5). The kit starts it with only the backend and the provider; what goes here is
# the project's design, reviewed like any other. Every ECS service and Lambda the release deploys
# comes from the kit's modules (../../modules), named <name>-production-<service>.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.64"
    }
  }
  # backend.hcl, written by aws-bootstrap.sh: the state bucket, this root's key, its KMS key and
  # S3's own lock file.
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = var.name
      Environment = "production"
      ManagedBy   = "terraform"
    }
  }
}
