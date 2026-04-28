locals {
  name_prefix = "contoso-${var.environment}"
  location    = var.location

  common_tags = {
    Environment = var.environment
    Project     = "contoso-migration"
    ManagedBy   = "terraform"
    CostCentre  = "IT-MIGRATION"
  }
}
