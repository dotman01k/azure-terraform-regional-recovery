variable "name" { type = string }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "subnet_id" { type = string }
variable "private_dns_zone_id" { type = string }
variable "tenant_id" { type = string }
variable "admin_object_id" { type = string }
variable "admin_group_name" { type = string }
variable "role" { type = string }
variable "source_server_id" {
  type    = string
  default = null
}
variable "geo_backup" {
  type    = bool
  default = false
}
variable "zone_redundant" {
  type    = bool
  default = false
}
variable "zone" {
  type    = string
  default = "1"
}
variable "standby_zone" {
  type    = string
  default = "2"
}
