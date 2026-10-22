mock_provider "azurerm" {}
variables {
  subscription_id = "00000000-0000-0000-0000-000000000001"
}
run "default_private_topology" {
  command = plan
  assert {
    condition     = length(azurerm_subnet.database) == 2 && length(azurerm_virtual_network_peering.cross_region) == 2
    error_message = "Both private regions and peerings are required."
  }
  assert {
    condition     = one(azurerm_network_security_group.database["primary"].security_rule).access == "Allow"
    error_message = "The initial primary must not be fenced."
  }
}
run "primary_fencing" {
  command = plan
  variables { fence_primary = true }
  assert {
    condition     = one(azurerm_network_security_group.database["primary"].security_rule).access == "Deny" && one(azurerm_network_security_group.database["recovery"].security_rule).access == "Allow"
    error_message = "Only the old primary must be fenced."
  }
}
run "reject_invalid_prefix" {
  command = plan
  variables { prefix = "INVALID!" }
  expect_failures = [var.prefix]
}
