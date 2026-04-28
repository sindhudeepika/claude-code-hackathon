output "webapp_fqdn"       { value = azurerm_container_app.webapp.latest_revision_fqdn }
output "acr_login_server"  { value = azurerm_container_registry.main.login_server }
