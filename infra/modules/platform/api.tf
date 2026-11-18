resource "aws_apigatewayv2_api" "main" {
  name          = local.name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  for_each               = toset(["ingest", "ack", "dashboard", "reports"])
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app[each.key].invoke_arn
  payload_format_version = "2.0"
}

locals {
  dashboard_routes = {
    "GET/dashboard/state"           = "dashboard"
    "POST/dashboard/readings"       = "dashboard"
    "POST/dashboard/ack"            = "dashboard"
    "POST/dashboard/devices"        = "dashboard"
    "POST/dashboard/incidents"      = "dashboard"
    "POST/dashboard/sessions/start" = "dashboard"
    "POST/dashboard/sessions/stop"  = "dashboard"
    "POST/dashboard/reports"        = "reports"
    "GET/dashboard/reports"         = "reports"
  }
}

resource "aws_apigatewayv2_route" "main" {
  for_each  = merge({ "POST /readings" = "ingest", "GET /ack" = "ack", "POST /ack" = "ack" }, { for route, fn in local.dashboard_routes : "${split("/", route)[0]} ${trimprefix(route, split("/", route)[0])}" => fn })
  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.value].id}"
}

resource "aws_apigatewayv2_stage" "main" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 5
    throttling_rate_limit  = 2
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId = "$context.requestId", status = "$context.status", routeKey = "$context.routeKey", latency = "$context.responseLatency"
      }
    )
  }
}
