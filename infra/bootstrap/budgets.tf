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
