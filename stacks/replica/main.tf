module "replica" {
  source              = "../../modules/database"
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.subnet_id
  private_dns_zone_id = var.private_dns_zone_id
  tenant_id           = var.tenant_id
  admin_object_id     = var.admin_object_id
  admin_group_name    = var.admin_group_name
  role                = "replica"
  source_server_id    = var.source_server_id
}
output "id" { value = module.replica.id }
output "fqdn" { value = module.replica.fqdn }
