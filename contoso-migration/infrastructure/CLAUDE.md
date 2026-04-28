# CLAUDE.md — infrastructure (contoso-migration/infrastructure)

## What This Is
Terraform IaC for the full Contoso Financial Azure target architecture. UK South only.
Not deployed to a live cloud — reads correctly and would deploy with `terraform apply`.

## Hard Rules (enforced by PreToolUse hook in root .claude/settings.json)
1. **No plaintext secrets in any `.tf` file.** Secrets go in `azurerm_key_vault_secret`.
   Use `data "azurerm_key_vault_secret"` to reference them from apps.
2. **No `public_network_access_enabled = true`** on PostgreSQL, Redis, or Storage resources.
3. **`location` must always be `var.location`** — never hardcode a region string.

## Naming Convention
All resource names follow: `{type-abbr}-contoso-{workload}-{env}`
Local variable `local.name_prefix = "contoso-${var.environment}"` is used throughout.

## Module Structure
```
modules/
  networking/   VNet, subnets, private DNS zones, NSGs
  webapp/       Container App Environment, Container App, ACR
  database/     PostgreSQL Flexible Server, private endpoint
  batch/        Container App Job, Storage Account for feeds
```

## State File
In a real deployment, state goes in Azure Blob Storage (`azurerm` backend). Never commit
`.tfstate` files. The backend block is in `main.tf` and commented out for local validation.

## Plan Mode
Always use Plan Mode before:
- Any change to `modules/networking/` (subnet changes affect all other modules)
- Any `azurerm_private_endpoint` addition or removal
- Changes to `azurerm_key_vault_access_policy`

## Preferred Patterns
- Use Managed Identity (`azurerm_user_assigned_identity`) for app-to-service auth.
  Never use storage account keys or DB passwords in Container App environment variables.
- Tag every resource with: `Environment`, `Project = "contoso-migration"`, `ManagedBy = "terraform"`.
- Private endpoints require a corresponding `azurerm_private_dns_zone_virtual_network_link`.
