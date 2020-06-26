variable "environment_prefix" {
  default = "dev"
}

variable "database_name" {
  type    = string
  default = "notification_api"
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

variable "workspace_iam_role" {
  default = "arn:aws:iam::437518843863:role/notification-deploy-role"
}

variable "region" {
  default = "us-east-2"
}

data "terraform_remote_state" "base_infrastructure" {
  backend = "s3"

  config = {
    bucket = "va-notification-terraform"
    key    = "base-infrastructure.tfstate"
    region = var.region
  }
}

variable "database_instance_type" {
  default = "db.t3.medium"
}
