variable "app_tag" {
  type = string
}

variable "notify_environment" {
  type    = string
  default = "development"
}

variable "database_name" {
  type    = string
  default = "notification_api"
}

data "aws_vpc" "notification" {
  cidr_block = "10.0.0.0/24"
}

data "aws_subnet" "public_az_a" {
  cidr_block = "10.0.0.128/26"
}

data "aws_subnet" "public_az_b" {
  cidr_block = "10.0.0.192/26"
}

data "aws_subnet" "private_az_a" {
  cidr_block = "10.0.0.64/26"
}

data "aws_subnet" "private_az_b" {
  cidr_block = "10.0.0.0/26"
}

data "aws_ecs_cluster" "notification_fargate" {
  cluster_name = "notification-fargate-cluster"
}

data "aws_ssm_parameter" "database_uri" {
  name = "/dev/notification-api/database/uri"
}

data "aws_ssm_parameter" "twilio_from_number" {
  name = "/dev/notification-api/twilio/from-number"
}

data "aws_ssm_parameter" "twilio_account_sid" {
  name = "/dev/notification-api/twilio/account-sid"
}

data "aws_ssm_parameter" "twilio_auth_token" {
  name = "/dev/notification-api/twilio/auth-token"
}

data "terraform_remote_state" "application_db" {
  backend = "s3"

  config = {
    bucket = "terraform-notification-test"
    key    = "notification-api-dev-db.tfstate"
    region = "us-east-2"
  }
}

variable "default_tags" {
  type = map(string)
  default = {
    Stack       = "application-infrastructure",
    Environment = "dev",
    Team        = "va-notify"
  }
}