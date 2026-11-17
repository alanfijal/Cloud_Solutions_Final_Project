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
