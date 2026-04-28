output "webapp_url" {
  description = "Public FQDN of the Container App"
  value       = module.webapp.webapp_fqdn
}

output "acr_login_server" {
  description = "Azure Container Registry login server"
  value       = module.webapp.acr_login_server
}

output "postgres_fqdn" {
  description = "PostgreSQL Flexible Server FQDN (private — accessible within VNet only)"
  value       = module.database.postgres_fqdn
  sensitive   = false
}

output "key_vault_uri" {
  description = "Azure Key Vault URI for secret references"
  value       = azurerm_key_vault.main.vault_uri
}

output "feed_storage_account_name" {
  description = "Storage Account name for batch feed files"
  value       = module.batch.storage_account_name
}
