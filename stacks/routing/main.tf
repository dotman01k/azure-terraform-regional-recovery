variable "resource_group_name" { type = string }
variable "zone_name" { type = string }
variable "writer_fqdn" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9-]+\\.postgres\\.database\\.azure\\.com$", var.writer_fqdn))
    error_message = "Use the canonical PostgreSQL TLS hostname."
  }
}
variable "epoch" {
  type = number
  validation {
    condition     = var.epoch >= 1 && floor(var.epoch) == var.epoch
    error_message = "Routing epoch must be a positive integer."
  }
}
resource "azurerm_private_dns_txt_record" "writer" {
  name                = "writer"
  resource_group_name = var.resource_group_name
  zone_name           = var.zone_name
  ttl                 = 30
  record { value = jsonencode({ host = var.writer_fqdn, epoch = var.epoch }) }
  lifecycle { prevent_destroy = true }
}
output "discovery_name" { value = "writer.${var.zone_name}" }
output "writer" { value = { host = var.writer_fqdn, epoch = var.epoch } }
