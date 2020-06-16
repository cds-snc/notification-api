variable "environment_prefix" {
  default = "dev"
}

variable "database_name" {
  type    = string
  default = "notification_api"
}

data "aws_vpc" "notification" {
  cidr_block = "10.0.0.0/24"
}

data "aws_subnet" "private_az_a" {
  cidr_block = "10.0.0.64/26"
}

data "aws_subnet" "private_az_b" {
  cidr_block = "10.0.0.0/26"
}

locals {
  default_tags = {
    Stack = "application-database",
    Environment = var.environment_prefix,
    Team = "va-notify"
    ManagedBy = "Terraform"
  }
}

variable "workspace_iam_roles" {
  default = {
    default = "arn:aws:iam::437518843863:role/notification-deploy-role"
  }
}
