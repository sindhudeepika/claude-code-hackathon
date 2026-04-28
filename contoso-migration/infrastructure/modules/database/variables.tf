variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "name_prefix"         { type = string }
variable "subnet_id"           { type = string }
variable "private_dns_zone_id" { type = string }
variable "admin_login"         { type = string }
variable "key_vault_id"        { type = string }
variable "tags"                { type = map(string) }
