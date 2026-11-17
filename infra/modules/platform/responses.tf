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
resource "aws_iam_role_policy" "sns_key" {
  role = aws_iam_role.lambda["dispatch"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"],
    Resource = "arn:aws:kms:${local.region}:${local.account}:key/*",
    Condition = { StringEquals = {
      "kms:ViaService"                         = "sns.${local.region}.amazonaws.com",
      "kms:CallerAccount"                      = local.account,
      "kms:EncryptionContext:aws:sns:topicArn" = [aws_sns_topic.alerts["staff"].arn, aws_sns_topic.alerts["manager"].arn]
    } }
  }] })
}
resource "aws_sns_topic_policy" "operations" {
  arn = aws_sns_topic.alerts["operations"].arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" },
    Action    = "sns:Publish", Resource = aws_sns_topic.alerts["operations"].arn,
    Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnLike = { "aws:SourceArn" = "arn:aws:cloudwatch:${local.region}:${local.account}:alarm:${local.name}-*" } }
  }] })
}
