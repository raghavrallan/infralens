resource "azurerm_log_analytics_workspace" "app" {
  name                = "law-${var.name_prefix}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_monitor_action_group" "app" {
  name                = "ag-${var.name_prefix}"
  resource_group_name = azurerm_resource_group.app.name
  short_name          = "infralens"
  tags                = var.tags
}
