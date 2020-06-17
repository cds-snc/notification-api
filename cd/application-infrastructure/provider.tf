provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.workspace_iam_roles[terraform.workspace]
  }
}

terraform {
  backend "s3" {
    bucket  = "terraform-notification-test"
    key     = "notification-api-dev.tfstate"
    region  = var.region
    encrypt = true
  }
}