mock_provider "azurerm" {}
variables {
  subscription_id     = "00000000-0000-0000-0000-000000000001"
  resource_group_name = "rg-drpg-recovery"
  zone_name           = "drpg.recovery.internal"
  writer_fqdn         = "drpg-primary.postgres.database.azure.com"
  epoch               = 1
}
run "canonical_tls_discovery" {
  command = plan
  assert {
    condition     = jsondecode(one(azurerm_private_dns_txt_record.writer.record).value).host == var.writer_fqdn && azurerm_private_dns_txt_record.writer.ttl == 30
    error_message = "Publish canonical hostname in a short-lived TXT contract."
  }
}
run "invalid_epoch" {
  command = plan
  variables { epoch = 0 }
  expect_failures = [var.epoch]
}
run "alias_host_rejected" {
  command = plan
  variables { writer_fqdn = "writer.internal" }
  expect_failures = [var.writer_fqdn]
}
