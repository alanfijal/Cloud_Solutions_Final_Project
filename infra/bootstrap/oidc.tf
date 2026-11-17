resource "aws_iam_openid_connect_provider" "github" {
  count          = var.enable_github_oidc && var.existing_oidc_provider_arn == null ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  oidc = var.enable_github_oidc ? (var.existing_oidc_provider_arn != null ? var.existing_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn) : null
}

resource "aws_iam_role" "github" {
  for_each             = var.enable_github_oidc ? toset(["plan", "apply"]) : toset([])
  name                 = "coldchain-ci-${each.key}"
  max_session_duration = 3600
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Federated = local.oidc }, Action = "sts:AssumeRoleWithWebIdentity", Condition = { StringEquals = {
    "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub" = each.key == "apply" ? "repo:${var.repository}:environment:aws-deploy" : "repo:${var.repository}:ref:refs/heads/${var.branch}"
  } } }] })
}

resource "aws_iam_role_policy" "apply" {
  count  = var.enable_github_oidc ? 1 : 0
  role   = aws_iam_role.github["apply"].id
  policy = file(var.apply_policy_file)
}

resource "aws_iam_role_policy" "plan" {
  count = var.enable_github_oidc ? 1 : 0
  role  = aws_iam_role.github["plan"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.state.arn, Condition = { StringLike = { "s3:prefix" = ["coldchain/*"] } } },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.state.arn}/coldchain/*" },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.state.arn}/coldchain/*.tflock" },
    { Effect = "Allow", Action = ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:ListTags", "lambda:GetPolicy", "lambda:GetFunctionCodeSigningConfig"], Resource = "arn:aws:lambda:eu-north-1:028718095604:function:coldchain-*" },
    { Effect = "Allow", Action = ["dynamodb:DescribeTable", "dynamodb:DescribeContinuousBackups", "dynamodb:DescribeTimeToLive", "dynamodb:ListTagsOfResource"], Resource = "arn:aws:dynamodb:eu-north-1:028718095604:table/coldchain-*" },
    { Effect = "Allow", Action = ["events:DescribeEventBus", "events:DescribeRule", "events:ListTargetsByRule", "events:ListTagsForResource"], Resource = ["arn:aws:events:eu-north-1:028718095604:event-bus/coldchain-*", "arn:aws:events:eu-north-1:028718095604:rule/coldchain-*/*"] },
    { Effect = "Allow", Action = ["sqs:GetQueueAttributes", "sqs:ListQueueTags"], Resource = "arn:aws:sqs:eu-north-1:028718095604:coldchain-*" },
    { Effect = "Allow", Action = ["sns:GetTopicAttributes", "sns:ListTagsForResource", "sns:GetSubscriptionAttributes"], Resource = "arn:aws:sns:eu-north-1:028718095604:coldchain-*" },
    { Effect = "Allow", Action = ["iam:GetRole", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:GetRolePolicy"], Resource = "arn:aws:iam::028718095604:role/coldchain-*" },
    { Effect = "Allow", Action = ["states:DescribeStateMachine", "states:ListTagsForResource"], Resource = "arn:aws:states:eu-north-1:028718095604:stateMachine:coldchain-*" },
    { Effect = "Allow", Action = ["athena:GetWorkGroup", "athena:ListTagsForResource"], Resource = "arn:aws:athena:eu-north-1:028718095604:workgroup/coldchain-*" },
    { Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetTags"], Resource = ["arn:aws:glue:eu-north-1:028718095604:catalog", "arn:aws:glue:eu-north-1:028718095604:database/coldchain_*", "arn:aws:glue:eu-north-1:028718095604:table/coldchain_*/*"] },
    { Effect = "Allow", Action = ["s3:GetBucket*", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:ListBucket"], Resource = "arn:aws:s3:::coldchain-*-028718095604-*" },
    { Effect = "Allow", Action = ["apigateway:GET"], Resource = "arn:aws:apigateway:eu-north-1::/apis/*" },
    { Effect = "Allow", Action = ["lambda:ListEventSourceMappings", "lambda:GetEventSourceMapping", "logs:DescribeLogGroups", "logs:ListTagsForResource", "cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource", "sts:GetCallerIdentity"], Resource = "*" }
  ] })
}
