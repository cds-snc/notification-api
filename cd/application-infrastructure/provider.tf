provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.workspace_iam_roles[terraform.workspace]
  }
}

terraform {
  backend "s3" {
    bucket = "va-notification-terraform"
    key    = "application-infrastructure.tfstate"
    region  = "us-east-2"
    encrypt = true
  }
}