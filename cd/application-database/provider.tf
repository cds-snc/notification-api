provider "aws" {
  region = "us-east-2"

  assume_role {
    role_arn     = var.workspace_iam_role
  }
}

terraform {
  backend "s3" {
    bucket  = "terraform-notification-test"
    key     = "notification-api-dev-db.tfstate"
    region  = "us-east-2"
    encrypt = true
  }
}