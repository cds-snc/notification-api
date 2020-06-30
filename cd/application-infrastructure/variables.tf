variable "environment_prefix" {
  default = "dev"
}

variable "database_name" {
  type    = string
  default = "notification_api"
}

variable "bucket" {
  default = "va-notification-terraform"
}

data "terraform_remote_state" "application_db" {
  backend = "s3"

  config = {
    bucket = var.bucket
    key    = "application-database.tfstate"
    region = var.region
  }
}

data "terraform_remote_state" "base_infrastructure" {
  backend = "s3"

  config = {
    bucket = var.bucket
    key    = "base-infrastructure.tfstate"
    region = var.region
  }
}

locals {
  default_tags = {
    Stack       = "application-infrastructure",
    Environment = var.environment_prefix,
    Team        = "va-notify"
    ManagedBy   = "Terraform"
  }
}

variable "deploy_role" {
    default = "arn:aws:iam::437518843863:role/notification-deploy-role"
}

variable "region" {
  default = "us-east-2"
}

variable "log_retention_in_days" {
  type = number
  description = "number of days to keep logs in cloud watch"
  default = 7
}