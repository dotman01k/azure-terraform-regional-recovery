mock_provider "azurerm" {}
variables {
  name                = "drpg-primary"
  resource_group_name = "rg-drpg-primary"
  location            = "eastus"
  subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-drpg-primary/providers/Microsoft.Network/virtualNetworks/vnet-drpg-primary/subnets/database"
  private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-drpg-recovery/providers/Microsoft.Network/privateDnsZones/drpg.postgres.database.azure.com"
  tenant_id           = "00000000-0000-0000-0000-000000000002"
  admin_object_id     = "00000000-0000-0000-0000-000000000003"
  admin_group_name    = "dr-pg-admins"
  role                = "primary"
  geo_backup          = true
  zone_redundant      = true
}
run "private_entra_only_primary" {
  command = plan
  assert {
    condition     = !azurerm_postgresql_flexible_server.this.public_network_access_enabled && azurerm_postgresql_flexible_server.this.authentication[0].active_directory_auth_enabled && !azurerm_postgresql_flexible_server.this.authentication[0].password_auth_enabled
    error_message = "Database must be private and Entra-only."
  }
  assert {
    condition     = azurerm_postgresql_flexible_server.this.high_availability[0].mode == "ZoneRedundant" && azurerm_postgresql_flexible_server.this.geo_redundant_backup_enabled
    error_message = "Primary needs HA and geo-redundant backups."
  }
}
run "replica_has_no_primary_ha" {
  command = plan
  variables {
    source_server_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-primary/providers/Microsoft.DBforPostgreSQL/flexibleServers/source-primary"
    zone_redundant   = false
    geo_backup       = false
  }
  assert {
    condition     = azurerm_postgresql_flexible_server.this.create_mode == "Replica" && length(azurerm_postgresql_flexible_server.this.high_availability) == 0
    error_message = "Read replica must use explicit replica creation and no initial HA block."
  }
}
run "replica_ha_combination_rejected" {
  command = plan
  variables {
    source_server_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-primary/providers/Microsoft.DBforPostgreSQL/flexibleServers/source-primary"
  }
  expect_failures = [azurerm_postgresql_flexible_server.this]
}
