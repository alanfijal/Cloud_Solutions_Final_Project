terraform {
  required_version = "= 1.17.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "= 6.21.0" }
  }
}
provider "aws" {
  region              = "eu-north-1"
  allowed_account_ids = ["028718095604"]
  default_tags { tags = { Project = "ColdChainMonitor", Owner = var.owner, Environment = "bootstrap" } }
}
provider "aws" {
  alias               = "billing"
  region              = "us-east-1"
  allowed_account_ids = ["028718095604"]
  default_tags { tags = { Project = "ColdChainMonitor", Owner = var.owner, Environment = "bootstrap" } }
}
variable "owner" {
  type    = string
  default = "esade-project"
}
variable "enable_github_oidc" {
  description = "Disabled for this account: AWS project policies deny IAM provider operations. Requires verified eligibility and separate scope approval."
  type        = bool
  default     = false
}
variable "repository" {
  type    = string
  default = "alanfijal/Cloud_Solutions_Final_Project"
}
variable "branch" {
  type    = string
  default = "main"
}
variable "budget_email" {
  type      = string
  sensitive = true
}
variable "period_start" {
  description = "Planning default; review the project budget window before initial deployment approval."
  type        = string
  default     = "2026-11-17_00:00"
}
variable "period_end" {
  description = "Budget end, not an automatic resource deletion date. No monthly reset during this project window."
  type        = string
  default     = "2026-12-17_00:00"
}
variable "existing_oidc_provider_arn" {
  type    = string
  default = null
}
variable "apply_policy_file" {
  description = "Owner-reviewed project-scoped policy; intentionally no administrator fallback."
  type        = string
  default     = null
  validation {
    condition     = !var.enable_github_oidc || var.apply_policy_file != null
    error_message = "OIDC activation requires an explicitly reviewed apply policy file."
  }
}
resource "aws_s3_bucket" "state" {
  bucket = "coldchain-028718095604-tfstate"
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_policy" "tls" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false" } } }] })
}
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "old-versions-and-incomplete-uploads"
    status = "Enabled"
    filter { prefix = "" }
    noncurrent_version_expiration { noncurrent_days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
  depends_on = [aws_s3_bucket_versioning.state]
}
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
resource "aws_budgets_budget" "period" {
  provider          = aws.billing
  name              = "coldchain-project-period-gross-account"
  budget_type       = "COST"
  limit_amount      = "25"
  limit_unit        = "USD"
  time_unit         = "ANNUALLY"
  time_period_start = var.period_start
  time_period_end   = var.period_end
  cost_types {
    include_credit  = false
    include_refund  = false
    include_tax     = true
    include_support = true
    use_blended     = false
  }
  dynamic "notification" {
    for_each = toset([5, 10, 20, 25])
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_email]
    }
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 25
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
output "backend_bucket" { value = aws_s3_bucket.state.id }
output "plan_role" { value = try(aws_iam_role.github["plan"].arn, null) }
output "apply_role" { value = try(aws_iam_role.github["apply"].arn, null) }
