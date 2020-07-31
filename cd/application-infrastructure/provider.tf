provider "aws" {
  version = "~> 2.70"
  region = var.region

  assume_role {
    role_arn = var.deploy_role
  }
}

terraform {
  backend "s3" {
    key     = "application-infrastructure.tfstate"
    encrypt = true
  }
}