module "platform" {
  source            = "../../modules/platform"
  environment       = "dev"
  owner             = var.owner
  ingestion_enabled = var.ingestion_enabled
  consumers_enabled = var.consumers_enabled
  staff_email       = var.alert_email
  manager_email     = var.alert_email
  units = { for i in range(5) : "unit-${i + 1}" => {
    threshold            = i % 2 == 0 ? 5 : -18
    direction            = "max"
    site_id              = "demo-site"
    credential_parameter = "/coldchain-dev/devices/unit-${i + 1}"
  } }
}
