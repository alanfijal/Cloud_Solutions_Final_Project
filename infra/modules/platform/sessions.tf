# No scheduled producer: each operator-created session has a deadline and step cap.
resource "aws_iam_role" "automation" {
  for_each = toset(["sessions", "reports"])
  name     = "${local.name}-${each.key}-states"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = {
      StringEquals = { "aws:SourceAccount" = local.account },
      ArnLike      = { "aws:SourceArn" = "arn:aws:states:${local.region}:${local.account}:stateMachine:${local.name}-${each.key}" }
    }
  }] })
}

resource "aws_iam_role_policy" "automation" {
  for_each = aws_iam_role.automation
  role     = each.value.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.app[each.key].arn },
    { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"], Resource = "*" }
  ] })
}

resource "aws_sfn_state_machine" "sessions" {
  name     = "${local.name}-sessions"
  role_arn = aws_iam_role.automation["sessions"].arn
  type     = "STANDARD"
  tracing_configuration { enabled = true }
  definition = jsonencode({
    StartAt = "Tick", TimeoutSeconds = 660,
    States = {
      Tick = {
        Type  = "Task", Resource = aws_lambda_function.app["sessions"].arn, Next = "Decision",
        Retry = [{ ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 2, MaxAttempts = 2, BackoffRate = 2, JitterStrategy = "FULL" }],
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "Finish" }]
      },
      Decision = { Type = "Choice", Choices = [{ Variable = "$.done", BooleanEquals = true, Next = "Done" }], Default = "Wait" },
      Wait     = { Type = "Wait", SecondsPath = "$.wait_s", Next = "Tick" },
      Finish = {
        Type       = "Task", Resource = aws_lambda_function.app["sessions"].arn,
        Parameters = { "session_id.$" = "$.session_id", action = "finish" }, End = true,
        Retry      = [{ ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 2, MaxAttempts = 1, BackoffRate = 2 }]
      },
      Done = { Type = "Succeed" }
    }
  })
}
