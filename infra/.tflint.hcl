# tflint's rules for infra/ (DESIGN.md §14.6). The gate runs tflint with this file and the AWS
# ruleset at exactly this version, which scripts/realm/tools.sh fetches and checks.
plugin "aws" {
  enabled = true
  version = "0.48.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
