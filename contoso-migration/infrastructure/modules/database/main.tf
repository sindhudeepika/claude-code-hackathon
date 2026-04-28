resource "random_password" "db_admin" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}?"
}

# Store DB password in Key Vault — never in tfvars or environment variables
resource "azurerm_key_vault_secret" "db_password" {
  name         = "db-admin-password"
  value        = random_password.db_admin.result
  key_vault_id = var.key_vault_id

  lifecycle {
    ignore_changes = [value]  # Don't rotate on every apply
  }
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "psql-${var.name_prefix}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  version                       = "16"
  administrator_login           = var.admin_login
  administrator_password        = random_password.db_admin.result
  storage_mb                    = 65536
  sku_name                      = "GP_Standard_D4s_v3"
  zone                          = "1"
  high_availability {
    mode                      = "ZoneRedundant"
    standby_availability_zone = "2"
  }
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false  # UK South only — no geo-replication for PII
  public_network_access_enabled = false  # Private endpoint only — PCI-DSS requirement

  delegated_subnet_id    = var.subnet_id
  private_dns_zone_id    = var.private_dns_zone_id

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = true
    tenant_id                     = data.azurerm_client_config.current.tenant_id
  }

  tags = var.tags
}

data "azurerm_client_config" "current" {}

# Enable pgaudit for PCI-DSS audit logging
resource "azurerm_postgresql_flexible_server_configuration" "pgaudit" {
  name      = "pgaudit.log"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "all"
}

resource "azurerm_postgresql_flexible_server_configuration" "ssl_min_version" {
  name      = "ssl_min_protocol_version"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "TLSv1.2"
}

# Reporting database
resource "azurerm_postgresql_flexible_server_database" "contoso" {
  name      = "contoso"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_GB.utf8"
}
