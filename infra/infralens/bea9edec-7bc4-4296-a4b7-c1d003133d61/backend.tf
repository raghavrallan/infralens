# Replace with your org's remote state. Local backend is for validate only.
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
