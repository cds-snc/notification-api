provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.workspace_iam_roles[terraform.workspace]
  }
}

terraform {
  backend "s3" {
    encrypt = true
  }
}