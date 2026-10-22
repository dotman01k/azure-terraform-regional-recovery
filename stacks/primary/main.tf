module "primary" {
  source              = "../../modules/database"
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.subnet_id
  private_dns_zone_id = var.private_dns_zone_id
  tenant_id           = var.tenant_id
  admin_object_id     = var.admin_object_id
  admin_group_name    = var.admin_group_name
  role                = "primary"
  geo_backup          = true
  zone_redundant      = true
}
output "id" { value = module.primary.id }
output "fqdn" { value = module.primary.fqdn }
