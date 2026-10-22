terraform {
  required_version = ">= 1.13.0, < 1.14.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "= 4.68.0" }
  }
  backend "azurerm" {}
}
provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}
variable "subscription_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.subscription_id))
    error_message = "Use a subscription GUID."
  }
}
