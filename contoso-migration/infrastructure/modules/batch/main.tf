resource "azurerm_user_assigned_identity" "batch" {
  name                = "id-batch-${var.name_prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_role_assignment" "batch_kv_secrets" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.batch.principal_id
}

# Storage Account for daily feed files — replaces on-prem NFS mount (finding #3)
resource "azurerm_storage_account" "feeds" {
  name                             = "sa${replace(var.name_prefix, "-", "")}feeds"
  resource_group_name              = var.resource_group_name
  location                         = var.location
  account_tier                     = "Standard"
  account_replication_type         = "LRS"
  min_tls_version                  = "TLS1_2"
  allow_nested_items_to_be_public  = false
  public_network_access_enabled    = false  # Private endpoint only

  blob_properties {
    delete_retention_policy {
      days = 30
    }
  }

  tags = var.tags
}

resource "azurerm_storage_container" "feeds" {
  name                  = "feeds"
  storage_account_name  = azurerm_storage_account.feeds.name
  container_access_type = "private"
}

# Grant batch identity Storage Blob Data Reader on feeds container
resource "azurerm_role_assignment" "batch_storage_reader" {
  scope                = azurerm_storage_account.feeds.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.batch.principal_id
}

# Store storage connection string in Key Vault
resource "azurerm_key_vault_secret" "feed_storage_connection" {
  name         = "feed-storage-connection"
  value        = azurerm_storage_account.feeds.primary_blob_connection_string
  key_vault_id = var.key_vault_id
}

resource "azurerm_container_app_job" "batch" {
  name                         = "job-batch-${var.name_prefix}"
  resource_group_name          = var.resource_group_name
  location                     = var.location
  container_app_environment_id = data.azurerm_container_app_environment.main.id

  replica_timeout_in_seconds = 3600  # 1 hour max
  replica_retry_limit        = 2

  schedule_trigger_config {
    cron_expression          = var.cron_schedule
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.batch.id]
  }

  template {
    container {
      name   = "batch"
      image  = var.batch_image
      cpu    = 1
      memory = "2Gi"

      env {
        name  = "DB_HOST"
        value = var.db_host
      }
      env {
        name  = "DB_NAME"
        value = "contoso"
      }
      env {
        name  = "DB_USER"
        value = "contosoadmin"
      }
      env {
        name        = "DB_PASSWORD"
        secret_name = "db-password"
      }
      env {
        name        = "FEED_STORAGE_CONNECTION"
        secret_name = "feed-storage-connection"
      }
      env {
        name  = "DB_SSLMODE"
        value = "require"
      }
    }
  }

  secret {
    name                = "db-password"
    key_vault_secret_id = var.db_password_secret_id
    identity            = azurerm_user_assigned_identity.batch.id
  }

  secret {
    name                = "feed-storage-connection"
    key_vault_secret_id = azurerm_key_vault_secret.feed_storage_connection.id
    identity            = azurerm_user_assigned_identity.batch.id
  }

  tags = var.tags
}

data "azurerm_container_app_environment" "main" {
  name                = "cae-${var.name_prefix}"
  resource_group_name = var.resource_group_name
}
