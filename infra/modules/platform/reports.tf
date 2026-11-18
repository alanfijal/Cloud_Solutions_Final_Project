# Query execution continues independently of the browser and is cancelled at 60s.
resource "aws_sfn_state_machine" "reports" {
  name     = "${local.name}-reports"
  role_arn = aws_iam_role.automation["reports"].arn
  type     = "STANDARD"
  tracing_configuration { enabled = true }
  definition = jsonencode({
    StartAt = "Advance", TimeoutSeconds = 90,
    States = {
      Advance = {
        Type  = "Task", Resource = aws_lambda_function.app["reports"].arn, Next = "Decision",
        Retry = [{ ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 1, MaxAttempts = 2, BackoffRate = 2, JitterStrategy = "FULL" }],
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "Cancel" }]
      },
      Decision = { Type = "Choice", Choices = [{ Variable = "$.done", BooleanEquals = true, Next = "Done" }], Default = "Wait" },
      Wait     = { Type = "Wait", Seconds = 2, Next = "Advance" },
      Cancel = {
        Type       = "Task", Resource = aws_lambda_function.app["reports"].arn,
        Parameters = { "request_id.$" = "$.request_id", action = "cancel" }, End = true,
        Retry      = [{ ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 1, MaxAttempts = 1, BackoffRate = 2 }]
      },
      Done = { Type = "Succeed" }
    }
  })
}
