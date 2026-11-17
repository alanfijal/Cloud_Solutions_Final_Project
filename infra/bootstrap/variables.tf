variable "owner" {
  type    = string
  default = "esade-project"
}

variable "enable_github_oidc" {
  description = "Disabled for this account: AWS project policies deny IAM provider operations. Requires verified eligibility and separate scope approval."
  type        = bool
  default     = false
}

variable "repository" {
  type    = string
  default = "alanfijal/Cloud_Solutions_Final_Project"
}

variable "branch" {
  type    = string
  default = "main"
}

variable "budget_email" {
  type      = string
  sensitive = true
}

variable "period_start" {
  description = "Planning default; review the project budget window before initial deployment approval."
  type        = string
  default     = "2026-11-17_00:00"
}

variable "period_end" {
  description = "Budget end, not an automatic resource deletion date. No monthly reset during this project window."
  type        = string
  default     = "2026-12-17_00:00"
}

variable "existing_oidc_provider_arn" {
  type    = string
  default = null
}

variable "apply_policy_file" {
  description = "Owner-reviewed project-scoped policy; intentionally no administrator fallback."
  type        = string
  default     = null
  validation {
    condition     = !var.enable_github_oidc || var.apply_policy_file != null
    error_message = "OIDC activation requires an explicitly reviewed apply policy file."
  }
}
