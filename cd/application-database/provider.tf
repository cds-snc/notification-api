provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.workspace_iam_role
  }
}

terraform {
  backend "s3" {
    bucket  = "terraform-notification-test"
    key     = "notification-api-dev-db.tfstate"
    region  = var.region
    encrypt = true
  }
}