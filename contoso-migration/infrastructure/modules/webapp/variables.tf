variable "resource_group_name"      { type = string }
variable "location"                 { type = string }
variable "name_prefix"              { type = string }
variable "subnet_id"                { type = string }
variable "acr_id"                   { type = string }
variable "webapp_image"             { type = string }
variable "db_host"                  { type = string }
variable "redis_host"               { type = string }
variable "key_vault_id"             { type = string }
variable "db_password_secret_id"    { type = string }
variable "redis_password_secret_id" { type = string }
variable "tags"                     { type = map(string) }
variable "min_replicas"             { type = number; default = 1 }
variable "max_replicas"             { type = number; default = 5 }
