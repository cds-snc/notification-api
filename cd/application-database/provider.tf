provider "aws" {
  region = var.region

  assume_role {
    role_arn = var.workspace_iam_role
  }
}

terraform {
  backend "s3" {
    key     = "application-database.tfstate"
    encrypt = true
  }
}