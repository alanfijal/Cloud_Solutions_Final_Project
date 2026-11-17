provider "aws" {
  region              = "eu-north-1"
  allowed_account_ids = ["028718095604"]
  default_tags { tags = { Project = "ColdChainMonitor", Environment = "demo", Owner = var.owner } }
}
