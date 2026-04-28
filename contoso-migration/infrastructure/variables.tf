variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod"
  }
}

variable "location" {
  description = "Azure region. Must be uksouth for data residency compliance."
  type        = string
  default     = "uksouth"

  validation {
    condition     = var.location == "uksouth"
    error_message = "location must be uksouth. PII data residency requires UK South. See ADR-002."
  }
}

variable "webapp_image" {
  description = "Container image for the customer portal, e.g. acrcontosoprod.azurecr.io/webapp:1.0.0"
  type        = string
}

variable "batch_image" {
  description = "Container image for the reconciliation job, e.g. acrcontosoprod.azurecr.io/batch:1.0.0"
  type        = string
}

variable "db_admin_login" {
  description = "PostgreSQL Flexible Server admin login (username only — password comes from Key Vault)"
  type        = string
  default     = "contosoadmin"
}

variable "alert_email" {
  description = "Email address for Azure Monitor alerts (batch failures, health check failures)"
  type        = string
}
