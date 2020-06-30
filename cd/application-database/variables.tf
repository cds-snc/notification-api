variable "environment_prefix" {
  default = "dev"
}

variable "workspace_iam_role" {
  default = "arn:aws:iam::437518843863:role/notification-deploy-role"
}

variable "region" {
  default = "us-east-2"
}

variable "bucket" {
  default = "va-notification-terraform"
}

data "terraform_remote_state" "base_infrastructure" {
  backend = "s3"

  config = {
    bucket = var.bucket
    key    = "base-infrastructure.tfstate"
    region = var.region
  }
}

variable "database_name" {
  type    = string
  default = "notification_api"
}

variable "database_instance_type" {
  default = "db.t3.medium"
}

variable "database_deletion_protection" {
  description = "If the DB instance should have deletion protection enabled"
  type        = bool
  default     = true
}

locals {
  default_tags = {
    Stack       = "application-database",
    Environment = var.environment_prefix,
    Team        = "va-notify"
    ManagedBy   = "Terraform"
  }
}
