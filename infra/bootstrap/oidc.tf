# GitHub's OIDC provider: a workflow's token becomes a short AWS session (DESIGN.md §14.4). An
# account has only one, so a second project sets create_oidc_provider = false and uses it.

locals {
  github_oidc = "https://token.actions.githubusercontent.com"
  oidc_arn = (var.create_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
  : data.aws_iam_openid_connect_provider.github[0].arn)
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = local.github_oidc
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = local.github_oidc
}
