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
