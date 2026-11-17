terraform {
  required_version = ">= 1.17.1, < 2.0.0"

  required_providers {
    bytepluscc = {
      source  = "byteplus-sdk/bytepluscc"
      version = "= 0.0.63"
    }
  }

  backend "local" {
    path = "seed-mcp-vke.tfstate"
  }
}

provider "bytepluscc" {
  region = var.region
}
