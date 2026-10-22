mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = { fqdn = "mock.postgres.database.azure.com" }
  }
}
variables {
  subscription_id     = "00000000-0000-0000-0000-000000000001"
  name                = "drpg-primary"
  resource_group_name = "rg-drpg-primary"
  location            = "eastus"
  subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-drpg-primary/providers/Microsoft.Network/virtualNetworks/vnet-drpg-primary/subnets/database"
  private_dns_zone_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-drpg-recovery/providers/Microsoft.Network/privateDnsZones/drpg.postgres.database.azure.com"
  tenant_id           = "00000000-0000-0000-0000-000000000002"
  admin_object_id     = "00000000-0000-0000-0000-000000000003"
  admin_group_name    = "dr-pg-admins"
}
run "database_wiring" {
  command = plan
  assert {
    condition     = module.primary.fqdn != ""
    error_message = "Database module must expose a connection hostname."
  }
}
