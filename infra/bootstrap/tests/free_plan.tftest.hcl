# Mocked provider: no AWS credentials, reads, or resource creation.
mock_provider "aws" {}
mock_provider "aws" { alias = "billing" }

run "free_plan_omits_oidc" {
  command = plan
  variables {
    budget_email = "alerts@example.com"
  }
  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0 && length(aws_iam_role.github) == 0
    error_message = "The default Free plan bootstrap must not create IAM identity providers or CI roles."
  }
  assert {
    condition     = length(aws_iam_role_policy.apply) == 0 && length(aws_iam_role_policy.plan) == 0
    error_message = "Disabled OIDC must not require or install pipeline IAM policies."
  }
  assert {
    condition     = aws_budgets_budget.period.cost_types[0].include_credit == false && aws_budgets_budget.period.limit_amount == "25"
    error_message = "Gross-usage budget planning must remain independent of promotional credits."
  }
}
