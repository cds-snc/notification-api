provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.deploy_role
  }
}

terraform {
  backend "s3" {
    bucket = "terraform-notification-test"
    key    = "notification-test.tfstate"
    region = var.region
    encrypt = true
  }
}