mock_provider "aws" {
  mock_resource "aws_iam_role" { defaults = { arn = "arn:aws:iam::028718095604:role/mock" } }
  mock_resource "aws_sns_topic" { defaults = { arn = "arn:aws:sns:eu-north-1:028718095604:mock" } }
  mock_resource "aws_sqs_queue" { defaults = { arn = "arn:aws:sqs:eu-north-1:028718095604:mock", url = "https://sqs.eu-north-1.amazonaws.com/028718095604/mock" } }
  mock_resource "aws_lambda_function" { defaults = { arn = "arn:aws:lambda:eu-north-1:028718095604:function:mock", invoke_arn = "arn:aws:apigateway:eu-north-1:lambda:path/2015-03-31/functions/arn:aws:lambda:eu-north-1:028718095604:function:mock/invocations" } }
  mock_resource "aws_dynamodb_table" { defaults = { arn = "arn:aws:dynamodb:eu-north-1:028718095604:table/mock", stream_arn = "arn:aws:dynamodb:eu-north-1:028718095604:table/mock/stream/2026-11-17T00:00:00.000" } }
  mock_resource "aws_cloudwatch_event_bus" { defaults = { arn = "arn:aws:events:eu-north-1:028718095604:event-bus/mock" } }
  mock_resource "aws_cloudwatch_event_rule" { defaults = { arn = "arn:aws:events:eu-north-1:028718095604:rule/mock" } }
  mock_resource "aws_cloudwatch_log_group" { defaults = { arn = "arn:aws:logs:eu-north-1:028718095604:log-group:mock" } }
  mock_resource "aws_sfn_state_machine" { defaults = { arn = "arn:aws:states:eu-north-1:028718095604:stateMachine:mock" } }
  mock_resource "aws_apigatewayv2_api" { defaults = { execution_arn = "arn:aws:execute-api:eu-north-1:028718095604:mock" } }
}

override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "028718095604", arn = "arn:aws:iam::028718095604:role/test", user_id = "test" }
}
override_data {
  target = data.aws_region.current
  values = { region = "eu-north-1" }
}
run "bounded_demo" {
  command = apply
  variables {
    environment   = "dev"
    owner         = "esade-project"
    staff_email   = "alerts@example.com"
    manager_email = "alerts@example.com"
    units         = { unit-1 = { threshold = 5, direction = "max", site_id = "demo-site", credential_parameter = "/coldchain-dev/devices/unit-1" } }
  }
  assert {
    condition     = alltrue([for q in aws_sqs_queue.main : q.visibility_timeout_seconds >= 6 * 25 + 5 && jsondecode(q.redrive_policy).maxReceiveCount == 5])
    error_message = "Queues need visibility headroom and finite redrive."
  }
  assert {
    condition     = alltrue([for f in aws_lambda_function.app : f.reserved_concurrent_executions == 2 && f.timeout == 25 && f.memory_size == 128])
    error_message = "Demo functions must remain bounded."
  }
  assert {
    condition     = aws_athena_workgroup.demo.configuration[0].enforce_workgroup_configuration && aws_athena_workgroup.demo.configuration[0].bytes_scanned_cutoff_per_query == 10485760
    error_message = "Athena scan limit must be enforced."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.incident.definition).TimeoutSeconds == 600
    error_message = "The workflow must have a ten-minute hard timeout."
  }
  assert {
    condition     = jsondecode(aws_iam_role.workflow.assume_role_policy).Statement[0].Condition.StringEquals["aws:SourceAccount"] == "028718095604" && jsondecode(aws_iam_role.workflow.assume_role_policy).Statement[0].Condition.ArnLike["aws:SourceArn"] == "arn:aws:states:eu-north-1:028718095604:stateMachine:coldchain-dev"
    error_message = "Workflow role trust must be scoped to this account and state machine."
  }

  assert {
    condition     = aws_s3_bucket_public_access_block.web.block_public_acls && aws_s3_bucket_public_access_block.web.block_public_policy && aws_s3_bucket_public_access_block.web.ignore_public_acls && aws_s3_bucket_public_access_block.web.restrict_public_buckets && aws_cloudfront_origin_access_control.web.signing_behavior == "always"
    error_message = "Frontend storage must remain private and accessible through signed CloudFront origin requests."
  }
  assert {
    condition     = aws_cloudfront_distribution.web.ordered_cache_behavior[0].cache_policy_id == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" && aws_cloudfront_distribution.web.ordered_cache_behavior[0].origin_request_policy_id == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    error_message = "Authenticated dashboard data must never be cached, and Authorization must reach API Gateway."
  }
  assert {
    condition     = length(aws_s3_object.web) == 3 && length(aws_lambda_permission.dashboard) == 3 && !contains(flatten([for p in local.permissions.dashboard : p.actions]), "dynamodb:PutItem")
    error_message = "The UI uses three static files, three scoped routes and read-only database access."
  }

}
