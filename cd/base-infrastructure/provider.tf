provider "aws" {
  region = var.region

  assume_role {
    role_arn = var.deploy_role
  }
}

terraform {
  backend "s3" {
    key     = "base-infrastructure.tfstate"
    encrypt = true
  }
}