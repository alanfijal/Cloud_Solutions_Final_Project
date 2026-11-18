locals {
  name      = "coldchain-${var.environment}"
  functions = toset(["ingest", "detector", "outbox", "dispatch", "workflow", "ack", "lake", "dashboard", "sessions", "reports"])
  account   = data.aws_caller_identity.current.account_id
  region    = data.aws_region.current.region
  table_arn = aws_dynamodb_table.state.arn
}
