resource "azurerm_redis_cache" "app" {
  name                          = "redis-${var.name_prefix}"
  location                      = azurerm_resource_group.app.location
  resource_group_name           = azurerm_resource_group.app.name
  capacity                      = 0
  family                        = "C"
  sku_name                      = "Basic"
  non_ssl_port_enabled          = false
  public_network_access_enabled = false
  tags                          = var.tags
}
