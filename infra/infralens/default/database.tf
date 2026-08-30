resource "azurerm_postgresql_flexible_server" "app" {
  name                          = "psql-${var.name_prefix}"
  resource_group_name           = azurerm_resource_group.app.name
  location                      = azurerm_resource_group.app.location
  version                       = "16"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  public_network_access_enabled = false
  tags                          = var.tags
}
