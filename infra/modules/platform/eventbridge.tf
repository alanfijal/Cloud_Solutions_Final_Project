resource "aws_cloudwatch_event_bus" "main" {
  name = local.name
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

resource "aws_cloudwatch_event_rule" "responses" {
  name           = "${local.name}-responses"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  event_pattern  = jsonencode({ source = ["coldchain"], "detail-type" = ["incident.opened", "notification.staff", "incident.escalated"] })
}

resource "aws_cloudwatch_event_target" "dispatch" {
  event_bus_name = aws_cloudwatch_event_bus.main.name
  rule           = aws_cloudwatch_event_rule.responses.name
  target_id      = "dispatch"
  arn            = aws_lambda_function.app["dispatch"].arn
  dead_letter_config { arn = aws_sqs_queue.dlq["delivery"].arn }
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 5
  }
  depends_on = [aws_sqs_queue_policy.events, aws_lambda_permission.events]
}

resource "aws_cloudwatch_event_rule" "workflow_failures" {
  name          = "${local.name}-workflow-failures"
  event_pattern = jsonencode({ source = ["aws.states"], "detail-type" = ["Step Functions Execution Status Change"], detail = { status = ["FAILED", "TIMED_OUT", "ABORTED"], stateMachineArn = [aws_sfn_state_machine.incident.arn] } })
}

resource "aws_cloudwatch_event_target" "workflow_failures" {
  rule      = aws_cloudwatch_event_rule.workflow_failures.name
  target_id = "record-failure"
  arn       = aws_lambda_function.app["workflow"].arn
  dead_letter_config { arn = aws_sqs_queue.dlq["delivery"].arn }
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 5
  }
  depends_on = [aws_sqs_queue_policy.events, aws_lambda_permission.events]
}
