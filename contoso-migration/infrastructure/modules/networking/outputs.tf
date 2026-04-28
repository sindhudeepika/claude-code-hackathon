output "vnet_id"                       { value = azurerm_virtual_network.main.id }
output "app_subnet_id"                 { value = azurerm_subnet.app.id }
output "data_subnet_id"                { value = azurerm_subnet.data.id }
output "postgres_private_dns_zone_id"  { value = azurerm_private_dns_zone.postgres.id }
output "redis_private_dns_zone_id"     { value = azurerm_private_dns_zone.redis.id }
output "kv_private_dns_zone_id"        { value = azurerm_private_dns_zone.keyvault.id }
output "acr_private_dns_zone_id"       { value = azurerm_private_dns_zone.acr.id }
