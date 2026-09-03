resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.name_prefix}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  tags                = var.tags
}
