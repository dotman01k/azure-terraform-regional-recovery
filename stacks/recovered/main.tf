module "recovered" {
  source              = "../../modules/database"
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.subnet_id
  private_dns_zone_id = var.private_dns_zone_id
  tenant_id           = var.tenant_id
  admin_object_id     = var.admin_object_id
  admin_group_name    = var.admin_group_name
  role                = "replica" # Retain the existing tag during adoption; update separately after recovery.
}
output "id" { value = module.recovered.id }
output "fqdn" { value = module.recovered.fqdn }
import {
  to = module.recovered.azurerm_postgresql_flexible_server.this
  id = var.server_id
}
import {
  to = module.recovered.azurerm_postgresql_flexible_server_active_directory_administrator.this
  id = "${var.server_id}/administrators/${var.admin_object_id}"
}
