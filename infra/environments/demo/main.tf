terraform {
  required_version = "= 1.17.0"
  required_providers { aws = { source = "hashicorp/aws", version = "= 6.21.0" } }
  backend "s3" {}
}
provider "aws" {
  region              = "eu-north-1"
  allowed_account_ids = ["028718095604"]
  default_tags { tags = { Project = "ColdChainMonitor", Environment = "demo", Owner = var.owner } }
}
variable "owner" {
  type    = string
  default = "esade-project"
}
variable "alert_email" {
  description = "One address can receive staff, manager and operations notifications for the demo."
  type        = string
  sensitive   = true
}
variable "ingestion_enabled" {
  type    = bool
  default = true
}
variable "consumers_enabled" {
  type    = bool
  default = true
}
module "platform" {
  source            = "../../modules/platform"
  environment       = "demo"
  owner             = var.owner
  ingestion_enabled = var.ingestion_enabled
  consumers_enabled = var.consumers_enabled
  staff_email       = var.alert_email
  manager_email     = var.alert_email
  units = { for i in range(5) : "unit-${i + 1}" => {
    threshold            = i % 2 == 0 ? 5 : -18
    direction            = "max"
    site_id              = "demo-site"
    credential_parameter = "/coldchain-demo/devices/unit-${i + 1}"
  } }
}
output "api_url" { value = module.platform.api_url }
