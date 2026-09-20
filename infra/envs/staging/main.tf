# Staging: the project's own architecture, from its C4 containers diagram
# (DESIGN.md §14.5). The kit starts it with only the backend and the provider; what goes here is
# the project's design, reviewed like any other. Every ECS service and Lambda the release deploys
# comes from the kit's modules (../../modules), named <name>-staging-<service>.

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
      Environment = "staging"
      ManagedBy   = "terraform"
    }
  }
}

# Staging's values for docs/design/infrastructure.md §6. Production calls the same module with
# 10.21.0.0/16 and protect = true, so the two can't drift apart.
module "env" {
  source           = "../../modules/tokelo-env"
  name             = var.name
  environment      = "staging"
  vpc_cidr         = "10.20.0.0/16"
  app_subnet_cidrs = ["10.20.1.0/24", "10.20.2.0/24"]
  db_subnet_cidrs  = ["10.20.11.0/24", "10.20.12.0/24"]
  protect          = false # staging is disposable; production sets it
}
