variable "assume_role_arn" {
  description = "IAM role to be assumed by AWS provider"
}

provider "aws" {
  version = "~> 2.70"
  region  = "us-gov-west-1"

  assume_role {
    role_arn = var.assume_role_arn
  }
}

terraform {
  backend "s3" {
    key      = "utility.tfstate"
    encrypt  = true
    bucket   = "vanotify-terraform-dev"
    region   = "us-gov-west-1"
    role_arn = "arn:aws-us-gov:iam::171875617347:role/project/project-terraform-state-mgm-dev"
  }
}