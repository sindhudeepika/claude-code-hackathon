variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_prefix" { type = string }
variable "tags" { type = map(string) }

variable "vnet_address_space" {
  type    = list(string)
  default = ["10.10.0.0/16"]
}

variable "app_subnet_cidr" {
  type    = string
  default = "10.10.1.0/24"
}

variable "data_subnet_cidr" {
  type    = string
  default = "10.10.2.0/24"
}
