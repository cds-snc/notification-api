provider "aws" {
  region = "us-east-2"

  assume_role {
    role_arn     = "arn:aws:iam::437518843863:role/notify-deploy-role"
  }
}

terraform {
  backend "s3" {
    bucket = "terraform-notification-test"
    key    = "notification-test.tfstate"
    region = "us-east-2"
  }
}