provider "aws" {
  region              = "eu-north-1"
  allowed_account_ids = ["028718095604"]
  default_tags { tags = { Project = "ColdChainMonitor", Environment = "dev", Owner = var.owner } }
}
