# Generated from the architecture model. Review before apply.
terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}

variable "location" {
  type    = string
  default = "eastus"
}

variable "name_prefix" {
  type    = string
  default = "infralens"
}

variable "tags" {
  type    = map(string)
  default = { product = "infralens", managed_by = "terraform" }
}

resource "azurerm_resource_group" "app" {
  name     = "rg-${var.name_prefix}-prod"
  location = var.location
  tags     = var.tags
}
