output "storage_account_name"        { value = azurerm_storage_account.feeds.name }
output "feeds_container_name"        { value = azurerm_storage_container.feeds.name }
output "batch_job_name"              { value = azurerm_container_app_job.batch.name }
