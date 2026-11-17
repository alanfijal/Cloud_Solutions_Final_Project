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
    dashboard = [{ actions = ["dynamodb:GetItem"], resources = [local.table_arn] }, {
      actions = ["ssm:GetParameter"], resources = concat(
        ["arn:aws:ssm:${local.region}:${local.account}:parameter/${local.name}/dashboard", "arn:aws:ssm:${local.region}:${local.account}:parameter/${local.name}/ack"],
        [for u in values(var.units) : "arn:aws:ssm:${local.region}:${local.account}:parameter${u.credential_parameter}"]
      )
    }]
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

resource "aws_iam_role" "workflow" {
  name = "${local.name}-states"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "states.amazonaws.com"
        }, Action = "sts:AssumeRole", Condition = {
        StringEquals = { "aws:SourceAccount" = local.account },
        ArnLike      = { "aws:SourceArn" = "arn:aws:states:${local.region}:${local.account}:stateMachine:${local.name}" }
      }
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
