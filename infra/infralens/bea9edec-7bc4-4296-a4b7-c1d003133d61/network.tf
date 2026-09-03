resource "azurerm_virtual_network" "app" {
  name                = "vnet-${var.name_prefix}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  address_space       = ["10.60.0.0/16"]
  tags                = var.tags
}

resource "azurerm_subnet" "data" {
  name                 = "snet-data"
  resource_group_name  = azurerm_resource_group.app.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.60.1.0/24"]
}

resource "azurerm_subnet" "runtime" {
  name                 = "snet-runtime"
  resource_group_name  = azurerm_resource_group.app.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.60.2.0/24"]
}
