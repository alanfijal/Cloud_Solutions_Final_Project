variable "environment" { type = string }
variable "owner" { type = string }
variable "staff_email" { type = string }
variable "manager_email" { type = string }
variable "units" {
  type = map(object({ threshold = number, direction = string, site_id = string, credential_parameter = string }))
  validation {
    condition     = length(var.units) >= 1 && length(var.units) <= 5 && alltrue([for u in values(var.units) : contains(["min", "max"], u.direction)])
    error_message = "Use one to five device slots, with threshold direction min or max."
  }
}
variable "consumers_enabled" {
  type    = bool
  default = true
}

variable "ingestion_enabled" {
  type    = bool
  default = true
}
