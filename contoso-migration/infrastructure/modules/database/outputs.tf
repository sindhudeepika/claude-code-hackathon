output "postgres_fqdn"          { value = azurerm_postgresql_flexible_server.main.fqdn }
output "db_password_secret_id"  { value = azurerm_key_vault_secret.db_password.id }
