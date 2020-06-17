provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.deploy_role
  }
}

terraform {
  backend "s3" {
    bucket = "va-notification-terraform"
    key    = "base-infrastructure.tfstate"
    region = "us-east-2"
    encrypt = true
  }
}