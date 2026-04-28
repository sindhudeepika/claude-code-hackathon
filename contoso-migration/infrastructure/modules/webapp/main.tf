data "azurerm_container_registry" "main" {
  # Referenced from root module — passed via acr_id
  resource_group_name = var.resource_group_name
  name                = split("/", var.acr_id)[8]
}

# Managed Identity for the webapp — no passwords in env vars
resource "azurerm_user_assigned_identity" "webapp" {
  name                = "id-webapp-${var.name_prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

# Grant webapp identity pull access to ACR
resource "azurerm_role_assignment" "webapp_acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.webapp.principal_id
}

# Grant webapp identity read access to Key Vault secrets
resource "azurerm_role_assignment" "webapp_kv_secrets" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.webapp.principal_id
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.name_prefix}"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  infrastructure_subnet_id   = var.subnet_id
  internal_load_balancer_enabled = false
  tags                       = var.tags
}

resource "azurerm_container_app" "webapp" {
  name                         = "app-webapp-${var.name_prefix}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.webapp.id]
  }

  registry {
    server   = data.azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.webapp.id
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "webapp"
      image  = var.webapp_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "NODE_ENV"
        value = "production"
      }
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
        secret_name = "db-password"  # Resolved via secret block below
      }
      env {
        name  = "DB_SSL"
        value = "true"
      }
      env {
        name  = "REDIS_HOST"
        value = var.redis_host
      }
      env {
        name  = "REDIS_TLS"
        value = "true"
      }
      env {
        name        = "REDIS_PASSWORD"
        secret_name = "redis-password"
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 3000
        initial_delay          = 10
        interval_seconds       = 30
        failure_count_threshold = 3
      }

      readiness_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 3000
        interval_seconds        = 10
        failure_count_threshold = 3
      }
    }
  }

  secret {
    name                = "db-password"
    key_vault_secret_id = var.db_password_secret_id
    identity            = azurerm_user_assigned_identity.webapp.id
  }

  secret {
    name                = "redis-password"
    key_vault_secret_id = var.redis_password_secret_id
    identity            = azurerm_user_assigned_identity.webapp.id
  }

  ingress {
    external_enabled = true
    target_port      = 3000
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  tags = var.tags
}

# Forward-declared — ACR is created in root module but referenced here for naming
resource "azurerm_container_registry" "main" {
  count               = 0  # Created in root module — this block exists for output reference only
  name                = "placeholder"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Premium"
}
