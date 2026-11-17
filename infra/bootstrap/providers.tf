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
