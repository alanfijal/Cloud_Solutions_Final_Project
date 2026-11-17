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
          "aws:SourceArn" = each.key == "detector" ? [aws_cloudwatch_event_rule.readings.arn] : each.key == "lake" ? [aws_cloudwatch_event_rule.history.arn] : [aws_cloudwatch_event_rule.readings.arn, aws_cloudwatch_event_rule.history.arn, aws_cloudwatch_event_rule.responses.arn, aws_cloudwatch_event_rule.workflow_failures.arn]
          }, StringEquals = {
          "aws:SourceAccount" = local.account
        }
      }
      }
    ]
    }
  )
}
