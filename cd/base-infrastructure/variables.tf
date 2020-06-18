variable "environment_prefix" {
  default = "dev"
}

locals {
  default_tags = {
    Stack = "base-infrastructure",
    Environment = var.environment_prefix,
    Team = "va-notify"
    ManagedBy = "Terraform"
  }
}

variable "deploy_role" {
  default = "arn:aws:iam::437518843863:role/notification-deploy-role"
}

variable "admin_principal" {
  default = "arn:aws:iam::437518843863:role/federated-admin"
}

variable "vpc_cidr" {
  default = "10.0.0.0/24"
}

variable "region" {
  default = "us-east-2"
}

data "aws_availability_zones" "available_zones" {
}
