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

resource "aws_sns_topic_policy" "operations" {
  arn = aws_sns_topic.alerts["operations"].arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" },
    Action    = "sns:Publish", Resource = aws_sns_topic.alerts["operations"].arn,
    Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnLike = { "aws:SourceArn" = "arn:aws:cloudwatch:${local.region}:${local.account}:alarm:${local.name}-*" } }
  }] })
}
