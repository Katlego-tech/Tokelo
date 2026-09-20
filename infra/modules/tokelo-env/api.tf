# The HTTP API (docs/design/infrastructure.md §6, "Identity and the API"; api.md §6).
#
# One HTTP API in front of the `api` function, which serves both the JSON API and the web app
# from its own image (ADR-0010). Because the app and the API share an origin there is no CORS
# configuration here at all.
#
# Everything under /api/ goes through the JWT authorizer, so a request with a bad token is
# refused by API Gateway and never reaches the function. /health, /config.json and the web app's
# files are open: the health check is the release pipeline's, and the app has to load before
# anyone can sign in.

resource "aws_apigatewayv2_api" "http" {
  name          = local.prefix
  description   = "${local.prefix}: the web app and the JSON API (ADR-0010)"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.api.alias_arn # live, never the function itself
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_authorizer" "tenants" {
  api_id           = aws_apigatewayv2_api.http.id
  name             = "${local.prefix}-tenants"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer   = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.tenants.id}"
    audience = [aws_cognito_user_pool_client.web.id]
  }
}

locals {
  # The web app and the two open endpoints (api.md §6). A longer literal prefix wins in API
  # Gateway's route selection, so /api/ below takes precedence over GET /{proxy+}.
  open_routes = ["GET /health", "GET /config.json", "GET /", "GET /{proxy+}"]
}

resource "aws_apigatewayv2_route" "open" {
  #checkov:skip=CKV_AWS_309:these four are the open ones by design (§6, ADR-0010): the release's health check, the web app's own files, and the settings the app needs before anyone can sign in. Everything under /api/ is behind the authorizer below
  for_each = toset(local.open_routes)

  api_id    = aws_apigatewayv2_api.http.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

# Every JSON endpoint, behind the authorizer. The function routes on routeKey from here.
resource "aws_apigatewayv2_route" "api" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "ANY /api/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.tenants.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  # A flood of requests can't run up the bill (§Threats).
  default_route_settings {
    throttling_rate_limit  = 10
    throttling_burst_limit = 20
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    # No request body, no headers: a log line says who asked for what and what they got.
    format = jsonencode({
      requestId   = "$context.requestId"
      requestTime = "$context.requestTime"
      method      = "$context.httpMethod"
      route       = "$context.routeKey"
      status      = "$context.status"
      latency     = "$context.responseLatency"
      integration = "$context.integrationErrorMessage"
    })
  }
}

# nosemgrep: terraform.aws.security.aws-cloudwatch-log-group-unencrypted.aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "api" {
  #checkov:skip=CKV_AWS_338:30 days is this project's retention everywhere (§6); a year of logs is a cost the budget doesn't carry
  #checkov:skip=CKV_AWS_158:CloudWatch encrypts logs at rest already; a customer key is USD 1 a month for control this project doesn't use
  name              = "/aws/apigateway/${local.prefix}"
  retention_in_days = var.log_retention_days
}

# Only this API may invoke the alias.
resource "aws_lambda_permission" "api" {
  statement_id  = "AllowInvokeFromHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = module.api.function_name
  qualifier     = "live"
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
