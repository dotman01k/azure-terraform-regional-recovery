resource "azurerm_postgresql_flexible_server" "this" {
  name                          = var.name
  resource_group_name           = var.resource_group_name
  location                      = var.location
  version                       = "16"
  sku_name                      = "GP_Standard_D2s_v3"
  storage_mb                    = 65536
  auto_grow_enabled             = true
  backup_retention_days         = 14
  geo_redundant_backup_enabled  = var.geo_backup
  delegated_subnet_id           = var.subnet_id
  private_dns_zone_id           = var.private_dns_zone_id
  public_network_access_enabled = false
  create_mode                   = var.source_server_id == null ? null : "Replica"
  source_server_id              = var.source_server_id
  zone                          = var.zone
  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
  }
  dynamic "high_availability" {
    for_each = var.zone_redundant ? [1] : []
    content {
      mode                      = "ZoneRedundant"
      standby_availability_zone = var.standby_zone
    }
  }
  lifecycle {
    prevent_destroy = true
    # Azure can change active/standby zones during HA failover. Do not move it back.
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
    precondition {
      condition     = !(var.zone_redundant && var.source_server_id != null)
      error_message = "The initial read replica cannot request primary HA."
    }
  }
  tags = { project = "terraform-regional-recovery", role = var.role }
}
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "this" {
  server_name         = azurerm_postgresql_flexible_server.this.name
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  object_id           = var.admin_object_id
  principal_name      = var.admin_group_name
  principal_type      = "Group"
  lifecycle { prevent_destroy = true }
}
output "id" { value = azurerm_postgresql_flexible_server.this.id }
output "fqdn" { value = azurerm_postgresql_flexible_server.this.fqdn }
