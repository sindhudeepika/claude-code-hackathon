variable "resource_group_name"    { type = string }
variable "location"               { type = string }
variable "name_prefix"            { type = string }
variable "subnet_id"              { type = string }
variable "batch_image"            { type = string }
variable "db_host"                { type = string }
variable "key_vault_id"           { type = string }
variable "db_password_secret_id"  { type = string }
variable "tags"                   { type = map(string) }
variable "cron_schedule"          { type = string; default = "0 2 * * *" }  # 02:00 UTC daily
