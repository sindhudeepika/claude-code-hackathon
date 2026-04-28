terraform {
  required_version = ">= 1.7.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.110"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Uncomment for live deployments — state stored in Azure Blob Storage (UK South)
  # backend "azurerm" {
  #   resource_group_name  = "rg-contoso-tfstate"
  #   storage_account_name = "sacontosotfstate"
  #   container_name       = "tfstate"
  #   key                  = "contoso-migration.tfstate"
  # }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
  }
}

data "azurerm_client_config" "current" {}

# ─── Resource Group ──────────────────────────────────────────────────────────
resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name_prefix}"
  location = local.location
  tags     = local.common_tags
}

# ─── Networking ──────────────────────────────────────────────────────────────
module "networking" {
  source              = "./modules/networking"
  resource_group_name = azurerm_resource_group.main.name
  location            = local.location
  name_prefix         = local.name_prefix
  tags                = local.common_tags
}

# ─── Azure Container Registry ────────────────────────────────────────────────
resource "azurerm_container_registry" "main" {
  name                = "acr${replace(local.name_prefix, "-", "")}"
  resource_group_name = azurerm_resource_group.main.name
  location            = local.location
  sku                 = "Premium"  # Required for private endpoints and geo-replication
  admin_enabled       = false      # Use Managed Identity, not admin credentials

  network_rule_set {
    default_action = "Deny"
    ip_rule        = []
  }

  tags = local.common_tags
}

resource "azurerm_private_endpoint" "acr" {
  name                = "pe-acr-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = local.location
  subnet_id           = module.networking.app_subnet_id

  private_service_connection {
    name                           = "psc-acr-${local.name_prefix}"
    private_connection_resource_id = azurerm_container_registry.main.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "pdns-acr"
    private_dns_zone_ids = [module.networking.acr_private_dns_zone_id]
  }

  tags = local.common_tags
}

# ─── Azure Key Vault ─────────────────────────────────────────────────────────
resource "azurerm_key_vault" "main" {
  name                        = "kv-${local.name_prefix}"
  resource_group_name         = azurerm_resource_group.main.name
  location                    = local.location
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  purge_protection_enabled    = true
  soft_delete_retention_days  = 90
  enable_rbac_authorization   = true

  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
    ip_rules       = []
  }

  tags = local.common_tags
}

resource "azurerm_private_endpoint" "key_vault" {
  name                = "pe-kv-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = local.location
  subnet_id           = module.networking.data_subnet_id

  private_service_connection {
    name                           = "psc-kv-${local.name_prefix}"
    private_connection_resource_id = azurerm_key_vault.main.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "pdns-kv"
    private_dns_zone_ids = [module.networking.kv_private_dns_zone_id]
  }

  tags = local.common_tags
}

# ─── Azure Cache for Redis ────────────────────────────────────────────────────
resource "azurerm_redis_cache" "main" {
  name                = "redis-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = local.location
  capacity            = 1
  family              = "C"
  sku_name            = "Standard"
  minimum_tls_version = "1.2"

  redis_configuration {
    maxmemory_policy = "allkeys-lru"
    # No external keepalive required — Azure Cache for Redis manages eviction natively
    # (resolves discovery finding #5)
  }

  tags = local.common_tags
}

resource "azurerm_private_endpoint" "redis" {
  name                = "pe-redis-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = local.location
  subnet_id           = module.networking.data_subnet_id

  private_service_connection {
    name                           = "psc-redis-${local.name_prefix}"
    private_connection_resource_id = azurerm_redis_cache.main.id
    subresource_names              = ["redisCache"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "pdns-redis"
    private_dns_zone_ids = [module.networking.redis_private_dns_zone_id]
  }

  tags = local.common_tags
}

# ─── Workload Modules ─────────────────────────────────────────────────────────
module "database" {
  source              = "./modules/database"
  resource_group_name = azurerm_resource_group.main.name
  location            = local.location
  name_prefix         = local.name_prefix
  subnet_id           = module.networking.data_subnet_id
  private_dns_zone_id = module.networking.postgres_private_dns_zone_id
  admin_login         = var.db_admin_login
  key_vault_id        = azurerm_key_vault.main.id
  tags                = local.common_tags
}

module "webapp" {
  source                     = "./modules/webapp"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = local.location
  name_prefix                = local.name_prefix
  subnet_id                  = module.networking.app_subnet_id
  acr_id                     = azurerm_container_registry.main.id
  webapp_image               = var.webapp_image
  db_host                    = module.database.postgres_fqdn
  redis_host                 = azurerm_redis_cache.main.hostname
  key_vault_id               = azurerm_key_vault.main.id
  db_password_secret_id      = module.database.db_password_secret_id
  redis_password_secret_id   = azurerm_redis_cache.main.primary_access_key  # stored in KV by module
  tags                       = local.common_tags
}

module "batch" {
  source              = "./modules/batch"
  resource_group_name = azurerm_resource_group.main.name
  location            = local.location
  name_prefix         = local.name_prefix
  subnet_id           = module.networking.app_subnet_id
  batch_image         = var.batch_image
  db_host             = module.database.postgres_fqdn
  key_vault_id        = azurerm_key_vault.main.id
  db_password_secret_id = module.database.db_password_secret_id
  tags                = local.common_tags
}
