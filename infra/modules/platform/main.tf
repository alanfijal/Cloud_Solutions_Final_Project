terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws", version = "= 6.21.0"
    }
  }
}
data "aws_caller_identity" "current" {
}
data "aws_region" "current" {
}
locals {
  name      = "coldchain-${var.environment}"
  functions = toset(["ingest", "detector", "outbox", "dispatch", "workflow", "ack", "lake"])
  account   = data.aws_caller_identity.current.account_id
  region    = data.aws_region.current.region
  table_arn = aws_dynamodb_table.state.arn
}
resource "aws_cloudwatch_event_bus" "main" {
  name = local.name
}
resource "aws_dynamodb_table" "state" {
  name         = local.name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"
  server_side_encryption {
    enabled = true
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}
resource "aws_sqs_queue" "dlq" {
  for_each                  = toset(["detector", "lake", "delivery", "stream", "async"])
  name                      = "${local.name}-${each.key}-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}
resource "aws_sqs_queue" "main" {
  for_each                   = toset(["detector", "lake"])
  name                       = "${local.name}-${each.key}"
  sqs_managed_sse_enabled    = true
  visibility_timeout_seconds = 180
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn, maxReceiveCount = 5
    }
  )
}
resource "aws_cloudwatch_event_rule" "readings" {
  name           = "${local.name}-readings"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  event_pattern = jsonencode({
    source = ["coldchain"], "detail-type" = ["reading.received"]
    }
  )
}
resource "aws_cloudwatch_event_rule" "history" {
  name           = "${local.name}-history"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  event_pattern = jsonencode({
    source = ["coldchain"]
    }
  )
}
resource "aws_cloudwatch_event_target" "queues" {
  for_each       = aws_sqs_queue.main
  rule           = each.key == "detector" ? aws_cloudwatch_event_rule.readings.name : aws_cloudwatch_event_rule.history.name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  arn            = each.value.arn
  target_id      = each.key
  dead_letter_config {
    arn = aws_sqs_queue.dlq["delivery"].arn
  }
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 5
  }
  depends_on = [aws_sqs_queue_policy.events]
}
resource "aws_sqs_queue_policy" "events" {
  for_each = merge(aws_sqs_queue.main, {
    delivery = aws_sqs_queue.dlq["delivery"]
    }
  )
  queue_url = each.value.url
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "events.amazonaws.com"
      }, Action = "sqs:SendMessage", Resource = each.value.arn,
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = [aws_cloudwatch_event_rule.readings.arn, aws_cloudwatch_event_rule.history.arn, aws_cloudwatch_event_rule.responses.arn, aws_cloudwatch_event_rule.workflow_failures.arn]
          }, StringEquals = {
          "aws:SourceAccount" = local.account
        }
      }
      }
    ]
    }
  )
}
resource "aws_sns_topic" "alerts" {
  for_each          = toset(["staff", "manager", "operations"])
  name              = "${local.name}-${each.key}"
  kms_master_key_id = each.key == "operations" ? null : "alias/aws/sns"
}
resource "aws_sns_topic_subscription" "email" {
  for_each  = aws_sns_topic.alerts
  topic_arn = each.value.arn
  protocol  = "email"
  endpoint  = each.key == "staff" ? var.staff_email : var.manager_email
}
resource "aws_s3_bucket" "data" {
  for_each      = toset(["lake", "queries"])
  bucket        = "${local.name}-${local.account}-${each.key}"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "data" {
  for_each                = aws_s3_bucket.data
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_bucket_versioning" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  rule {
    id     = "short-demo-retention"
    status = "Enabled"
    filter {
      prefix = ""
    }
    expiration {
      days = each.key == "lake" ? 14 : 7
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
  depends_on = [aws_s3_bucket_versioning.data]
}
resource "aws_s3_bucket_policy" "tls" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [each.value.arn, "${each.value.arn}/*"], Condition = {
        Bool = {
          "aws:SecureTransport" = "false"
        }
      }
      }
    ]
    }
  )
}
resource "aws_iam_role" "lambda" {
  for_each = local.functions
  name     = "${local.name}-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "lambda.amazonaws.com"
      }, Action = "sts:AssumeRole"
      }
    ]
    }
  )
}
resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = 7
}
locals {
  state_access  = [{ actions = ["dynamodb:GetItem", "dynamodb:PutItem"], resources = [local.table_arn] }]
  ack_secret    = [{ actions = ["ssm:GetParameter"], resources = ["arn:aws:ssm:${local.region}:${local.account}:parameter/${local.name}/ack"] }]
  async_failure = [{ actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.dlq["async"].arn] }]
  permissions = {
    ingest = [
      { actions = ["events:PutEvents"], resources = [aws_cloudwatch_event_bus.main.arn] },
      { actions = ["ssm:GetParameter"], resources = [for u in values(var.units) : "arn:aws:ssm:${local.region}:${local.account}:parameter${u.credential_parameter}"] }
    ]
    detector = concat(local.state_access, [
      { actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], resources = [aws_sqs_queue.main["detector"].arn] }
    ])
    workflow = concat(local.state_access, local.async_failure)
    ack      = concat(local.state_access, local.ack_secret)
    lake = [
      { actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], resources = [aws_sqs_queue.main["lake"].arn] },
      { actions = ["s3:PutObject"], resources = ["${aws_s3_bucket.data["lake"].arn}/raw/*"] }
    ]
    outbox = [
      { actions = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator"], resources = [aws_dynamodb_table.state.stream_arn] },
      { actions = ["dynamodb:ListStreams"], resources = ["*"] },
      { actions = ["events:PutEvents"], resources = [aws_cloudwatch_event_bus.main.arn] },
      { actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.dlq["stream"].arn] }
    ]
    dispatch = concat(local.ack_secret, local.async_failure, [
      { actions = ["dynamodb:GetItem"], resources = [local.table_arn] },
      { actions = ["states:StartExecution"], resources = ["arn:aws:states:${local.region}:${local.account}:stateMachine:${local.name}"] },
      { actions = ["sns:Publish"], resources = [aws_sns_topic.alerts["staff"].arn, aws_sns_topic.alerts["manager"].arn] }
    ])
  }
}
resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17", Statement = concat([{
      Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.lambda[each.key].arn}:*"
      }, {
      Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = "*"
      }
      ], [for p in local.permissions[each.key] : {
        Effect = "Allow", Action = p.actions, Resource = p.resources
      }
    ])
    }
  )
}
resource "aws_lambda_function" "app" {
  for_each         = local.functions
  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.13"
  handler          = "app.handlers.${each.key}"
  filename         = "${path.module}/../../../artifacts/app.zip"
  source_code_hash = filebase64sha256("${path.module}/../../../artifacts/app.zip")
  memory_size      = 128
  timeout          = 25
  tracing_config { mode = "Active" }
  reserved_concurrent_executions = 2
  environment {
    variables = {
      INGESTION_ENABLED = tostring(var.ingestion_enabled)
      TABLE             = aws_dynamodb_table.state.name
      BUS               = aws_cloudwatch_event_bus.main.name
      UNITS             = jsonencode(var.units)
      ACK_PARAMETER     = "/${local.name}/ack"
      WORKFLOW          = "arn:aws:states:${local.region}:${local.account}:stateMachine:${local.name}"
      API_URL           = aws_apigatewayv2_api.main.api_endpoint
      STAFF_TOPIC       = aws_sns_topic.alerts["staff"].arn
      MANAGER_TOPIC     = aws_sns_topic.alerts["manager"].arn
      LAKE              = aws_s3_bucket.data["lake"].id
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
resource "aws_apigatewayv2_api" "main" {
  name          = local.name
  protocol_type = "HTTP"
}
resource "aws_apigatewayv2_integration" "lambda" {
  for_each               = toset(["ingest", "ack"])
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app[each.key].invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_route" "main" {
  for_each = {
    "POST /readings" = "ingest", "GET /ack" = "ack", "POST /ack" = "ack"
  }
  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.value].id}"
}
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${local.name}"
  retention_in_days = 7
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
resource "aws_lambda_permission" "api" {
  for_each      = toset(["ingest", "ack"])
  statement_id  = "APIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
resource "aws_iam_role" "workflow" {
  name = "${local.name}-states"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "states.amazonaws.com"
      }, Action = "sts:AssumeRole"
      }
    ]
    }
  )
}
resource "aws_iam_role_policy" "workflow" {
  role = aws_iam_role.workflow.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.app["workflow"].arn
      }, {
      Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"], Resource = "*"
      }
    ]
    }
  )
}
resource "aws_sfn_state_machine" "incident" {
  name     = local.name
  role_arn = aws_iam_role.workflow.arn
  type     = "STANDARD"
  tracing_configuration { enabled = true }
  definition = jsonencode({
    StartAt = "Staff", TimeoutSeconds = 600,
    States = {
      Staff = {
        Type = "Task", Resource = aws_lambda_function.app["workflow"].arn, Parameters = {
          "unit_id.$" = "$.unit_id", "incident_id.$" = "$.incident_id", action = "staff"
          }, Next = "Wait", Retry = [{
            ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 2, MaxAttempts = 2, BackoffRate = 2, JitterStrategy = "FULL"
          }
        ]
      },
      Wait = {
        Type = "Wait", Seconds = 30, Next = "Check"
      },
      Check = {
        Type = "Task", Resource = aws_lambda_function.app["workflow"].arn, Parameters = {
          "unit_id.$" = "$.unit_id", "incident_id.$" = "$.incident_id", action = "check"
          }, Next = "Decision", Retry = [{
            ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 2, MaxAttempts = 2, BackoffRate = 2, JitterStrategy = "FULL"
          }
        ]
      },
      Decision = {
        Type = "Choice", Choices = [{
          Variable = "$.status", StringEquals = "waiting", Next = "Wait"
          }
        ], Default = "Done"
      },
      Done = {
        Type = "Succeed"
      }
    }
    }
  )
}
resource "aws_glue_catalog_database" "lake" {
  name = replace(local.name, "-", "_")
}
resource "aws_glue_catalog_table" "events" {
  database_name = aws_glue_catalog_database.lake.name
  name          = "events"
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    EXTERNAL = "TRUE", classification = "json"
  }
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data["lake"].id}/raw/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }
    dynamic "columns" {
      for_each = {
        event_id = "string", event_type = "string", unit_id = "string", reading_id = "string", incident_id = "string", observed_at = "string", temperature = "double", detail = "string"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}
resource "aws_athena_workgroup" "demo" {
  name          = local.name
  force_destroy = false
  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = 10485760
    publish_cloudwatch_metrics_enabled = true
    result_configuration {
      output_location = "s3://${aws_s3_bucket.data["queries"].id}/results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
resource "aws_cloudwatch_metric_alarm" "dlq" {
  for_each    = aws_sqs_queue.dlq
  alarm_name  = "${local.name}-${each.key}-dlq"
  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  dimensions = {
    QueueName = each.value.name
  }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts["operations"].arn]
}
output "api_url" {
  value = aws_apigatewayv2_api.main.api_endpoint
}
output "lake_bucket" {
  value = aws_s3_bucket.data["lake"].id
}
output "table_name" {
  value = aws_dynamodb_table.state.name
}
