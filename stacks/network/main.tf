variable "prefix" {
  type    = string
  default = "drpg"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,9}$", var.prefix))
    error_message = "Prefix must be 3..10 lowercase letters/digits."
  }
}
variable "regions" {
  type = map(object({ location = string, cidr = string, database_cidr = string, client_cidr = string }))
  default = {
    primary  = { location = "eastus", cidr = "10.60.0.0/16", database_cidr = "10.60.0.0/24", client_cidr = "10.60.1.0/24" }
    recovery = { location = "westus3", cidr = "10.61.0.0/16", database_cidr = "10.61.0.0/24", client_cidr = "10.61.1.0/24" }
  }
  validation {
    condition = (toset(keys(var.regions)) == toset(["primary", "recovery"]) &&
      var.regions["primary"].location != var.regions["recovery"].location &&
    alltrue([for v in values(var.regions) : can(cidrnetmask(v.cidr)) && can(cidrnetmask(v.database_cidr)) && can(cidrnetmask(v.client_cidr))]))
    error_message = "Supply primary/recovery in distinct regions with IPv4 CIDRs."
  }
}
variable "fence_primary" {
  type    = bool
  default = false
}
locals { tags = { project = "terraform-regional-recovery" } }
# Resource groups are bootstrap prerequisites with RG-scoped deployment grants.
data "azurerm_resource_group" "region" {
  for_each = var.regions
  name     = "rg-${var.prefix}-${each.key}"
}
resource "azurerm_virtual_network" "region" {
  for_each            = var.regions
  name                = "vnet-${var.prefix}-${each.key}"
  resource_group_name = data.azurerm_resource_group.region[each.key].name
  location            = each.value.location
  address_space       = [each.value.cidr]
  tags                = local.tags
}
resource "azurerm_subnet" "database" {
  for_each             = var.regions
  name                 = "database"
  resource_group_name  = data.azurerm_resource_group.region[each.key].name
  virtual_network_name = azurerm_virtual_network.region[each.key].name
  address_prefixes     = [each.value.database_cidr]
  service_endpoints    = ["Microsoft.Storage"]
  delegation {
    name = "postgresql"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "client" {
  for_each             = var.regions
  name                 = "clients"
  resource_group_name  = data.azurerm_resource_group.region[each.key].name
  virtual_network_name = azurerm_virtual_network.region[each.key].name
  address_prefixes     = [each.value.client_cidr]
}
resource "azurerm_network_security_group" "database" {
  for_each            = var.regions
  name                = "nsg-${var.prefix}-${each.key}-database"
  resource_group_name = data.azurerm_resource_group.region[each.key].name
  location            = each.value.location
  security_rule {
    name                       = "database-client-fence"
    priority                   = 100
    direction                  = "Inbound"
    access                     = each.key == "primary" && var.fence_primary ? "Deny" : "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = each.key == "primary" && var.fence_primary ? "*" : "VirtualNetwork"
    destination_address_prefix = "*"
  }
  tags = local.tags
}
resource "azurerm_subnet_network_security_group_association" "database" {
  for_each                  = var.regions
  subnet_id                 = azurerm_subnet.database[each.key].id
  network_security_group_id = azurerm_network_security_group.database[each.key].id
}
resource "azurerm_virtual_network_peering" "cross_region" {
  for_each                     = var.regions
  name                         = "to-${each.key == "primary" ? "recovery" : "primary"}"
  resource_group_name          = data.azurerm_resource_group.region[each.key].name
  virtual_network_name         = azurerm_virtual_network.region[each.key].name
  remote_virtual_network_id    = azurerm_virtual_network.region[each.key == "primary" ? "recovery" : "primary"].id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = false
}
resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.prefix}.postgres.database.azure.com"
  resource_group_name = data.azurerm_resource_group.region["recovery"].name
  tags                = local.tags
}
resource "azurerm_private_dns_zone" "routing" {
  name                = "${var.prefix}.recovery.internal"
  resource_group_name = data.azurerm_resource_group.region["recovery"].name
  tags                = local.tags
}
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  for_each              = var.regions
  name                  = "postgres-${each.key}"
  resource_group_name   = data.azurerm_resource_group.region["recovery"].name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.region[each.key].id
  registration_enabled  = false
}
resource "azurerm_private_dns_zone_virtual_network_link" "routing" {
  for_each              = var.regions
  name                  = "routing-${each.key}"
  resource_group_name   = data.azurerm_resource_group.region["recovery"].name
  private_dns_zone_name = azurerm_private_dns_zone.routing.name
  virtual_network_id    = azurerm_virtual_network.region[each.key].id
  registration_enabled  = false
}
output "contract" {
  value = {
    resource_groups  = { for k, v in data.azurerm_resource_group.region : k => v.name }
    database_subnets = { for k, v in azurerm_subnet.database : k => v.id }
    nsg_ids          = { for k, v in azurerm_network_security_group.database : k => v.id }
    locations        = { for k, v in var.regions : k => v.location }
    postgres_zone_id = azurerm_private_dns_zone.postgres.id
    routing_zone     = azurerm_private_dns_zone.routing.name
  }
  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres, azurerm_subnet_network_security_group_association.database]
}
