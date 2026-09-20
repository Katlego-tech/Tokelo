# Identity (docs/design/infrastructure.md §6, "Identity and the API"; api.md §4).
#
# One Cognito user pool per environment. A tenant signs up with an email address, verifies it,
# and signs in; the token's `sub` is their tenant ID, so there is no second identity to keep in
# step (domain-model.md §3). API Gateway checks the token before a request reaches a function
# (api.tf), so the `api` only ever sees a verified claim.

resource "aws_cognito_user_pool" "tenants" {
  #checkov:skip=CKV_AWS_342:advanced security is charged per monthly active user and needs the Plus plan; the Lite plan is what the free plan carries (ADR-0003)
  name = local.prefix

  # The email address is the username, and it has to be verified before it is of any use.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12 # long beats clever: no composition rules beyond this
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 1
  }

  # TOTP if the tenant wants it. Requiring it would lock out a tenant who is holding a lease
  # dispute and a borrowed phone, which is exactly who this is for.
  mfa_configuration = "OPTIONAL"
  software_token_mfa_configuration {
    enabled = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Cognito's own sender: a small daily limit, enough for an elective's sign-ups (§10). SES is
  # the change if it isn't.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Your Tokelo verification code"
    email_message        = "Your Tokelo verification code is {####}. Tokelo gives legal information, not legal advice."
  }

  admin_create_user_config {
    allow_admin_create_user_only = false # tenants sign themselves up (REQ-001)
  }

  user_pool_tier = "LITE"

  deletion_protection = var.protect ? "ACTIVE" : "INACTIVE"
}

# The web app's client: public, because a single-page app can keep no secret.
resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.prefix}-web"
  user_pool_id = aws_cognito_user_pool.tenants.id

  generate_secret = false
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",     # the password never crosses the wire
    "ALLOW_REFRESH_TOKEN_AUTH" # and the refresh token keeps the session
  ]

  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  prevent_user_existence_errors = "ENABLED" # "wrong email or password", never which one
  enable_token_revocation       = true
}
