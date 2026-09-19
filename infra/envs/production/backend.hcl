# Written by scripts/realm/aws-bootstrap.sh: where this root's state lives (DESIGN.md §14.5).
bucket       = "tokelo-tfstate-753176172735"
key          = "envs/production/terraform.tfstate"
region       = "eu-west-1"
encrypt      = true
kms_key_id   = "arn:aws:kms:eu-west-1:753176172735:key/884bc86e-ee89-4105-851c-d727c8462d99"
use_lockfile = true
