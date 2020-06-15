provider "aws" {
  region = "us-east-2"

  assume_role {
    role_arn     = var.workspace_iam_roles[terraform.workspace]
  }
}

terraform {
  backend "s3" {
    bucket  = "terraform-notification-test"
    key     = "notification-api-dev.tfstate"
    region  = "us-east-2"
    encrypt = true
  }
}