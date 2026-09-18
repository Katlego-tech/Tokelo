# The budget (DESIGN.md §14.10): a monthly limit that emails at 50%, 80% and 100% of what's spent,
# and when the month's forecast passes it. It warns; it stops nothing.
#
# Credits don't count (decided 2026-09-18): AWS subtracts them by default, so on an account
# running on credits, such as a free-plan account, spend would read zero and no alert would fire
# while the credits drain.

locals {
  alerts = {
    actual-50      = { type = "ACTUAL", percent = 50 }
    actual-80      = { type = "ACTUAL", percent = 80 }
    actual-100     = { type = "ACTUAL", percent = 100 }
    forecasted-100 = { type = "FORECASTED", percent = 100 }
  }
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
  }

  dynamic "notification" {
    for_each = local.alerts
    content {
      notification_type          = notification.value.type
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.percent
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = [var.budget_email]
    }
  }
}
