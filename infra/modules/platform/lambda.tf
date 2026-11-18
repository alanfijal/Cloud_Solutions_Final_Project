resource "aws_lambda_function" "app" {
  for_each         = local.functions
  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.13"
  handler          = lookup({ dashboard = "app.dashboard.handler", sessions = "app.sessions.tick", reports = "app.reports.handler" }, each.key, "app.handlers.${each.key}")
  filename         = "${path.module}/../../../artifacts/app.zip"
  source_code_hash = filebase64sha256("${path.module}/../../../artifacts/app.zip")
  memory_size      = 128
  timeout          = 25
  tracing_config { mode = "Active" }
  reserved_concurrent_executions = 2
  environment {
    variables = {
      INGESTION_ENABLED   = tostring(var.ingestion_enabled)
      TABLE               = aws_dynamodb_table.state.name
      BUS                 = aws_cloudwatch_event_bus.main.name
      UNITS               = jsonencode(var.units)
      ACK_PARAMETER       = "/${local.name}/ack"
      DASHBOARD_PARAMETER = "/${local.name}/dashboard"
      WORKFLOW            = "arn:aws:states:${local.region}:${local.account}:stateMachine:${local.name}"
      API_URL             = aws_apigatewayv2_api.main.api_endpoint
      STAFF_TOPIC         = aws_sns_topic.alerts["staff"].arn
      MANAGER_TOPIC       = aws_sns_topic.alerts["manager"].arn
      LAKE                = aws_s3_bucket.data["lake"].id
      SESSION_WORKFLOW    = "arn:aws:states:${local.region}:${local.account}:stateMachine:${local.name}-sessions"
      REPORT_WORKFLOW     = "arn:aws:states:${local.region}:${local.account}:stateMachine:${local.name}-reports"
      ATHENA_WORKGROUP    = local.name
      CATALOG_DATABASE    = replace(local.name, "-", "_")
    }
  }
  depends_on = [aws_iam_role_policy.lambda]
}

resource "aws_lambda_event_source_mapping" "queues" {
  for_each                           = aws_sqs_queue.main
  event_source_arn                   = each.value.arn
  function_name                      = aws_lambda_function.app[each.key].arn
  enabled                            = var.consumers_enabled
  batch_size                         = 10
  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = 2
  }
}

resource "aws_lambda_event_source_mapping" "outbox" {
  event_source_arn               = aws_dynamodb_table.state.stream_arn
  function_name                  = aws_lambda_function.app["outbox"].arn
  starting_position              = "TRIM_HORIZON"
  enabled                        = var.consumers_enabled
  batch_size                     = 10
  maximum_retry_attempts         = 5
  maximum_record_age_in_seconds  = 3600
  bisect_batch_on_function_error = true
  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.dlq["stream"].arn
    }
  }
  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT"], dynamodb = {
          Keys = {
            pk = {
              S = [{
                prefix = "OUT#"
                }
              ]
            }
          }
        }
        }
      )
    }
  }
}

resource "aws_lambda_permission" "api" {
  for_each       = toset(["ingest", "ack"])
  statement_id   = "APIGateway"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.app[each.key].function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = each.key == "ingest" ? "${aws_apigatewayv2_api.main.execution_arn}/*/POST/readings" : "${aws_apigatewayv2_api.main.execution_arn}/*/*/ack"
  source_account = local.account
}

resource "aws_lambda_permission" "dashboard" {
  for_each       = local.dashboard_routes
  statement_id   = "Dashboard${replace(replace(each.key, "/", ""), "-", "")}"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.app[each.value].function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_apigatewayv2_api.main.execution_arn}/*/${each.key}"
  source_account = local.account
}

resource "aws_lambda_permission" "events" {
  for_each       = { dispatch = aws_cloudwatch_event_rule.responses.arn, workflow = aws_cloudwatch_event_rule.workflow_failures.arn }
  statement_id   = "EventBridge"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.app[each.key].function_name
  principal      = "events.amazonaws.com"
  source_arn     = each.value
  source_account = local.account
}

resource "aws_lambda_function_event_invoke_config" "events" {
  for_each                     = toset(["dispatch", "workflow"])
  function_name                = aws_lambda_function.app[each.key].function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600
  destination_config {
    on_failure { destination = aws_sqs_queue.dlq["async"].arn }
  }
}
