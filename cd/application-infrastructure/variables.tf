variable "app_tag" {
  type = string
}

variable "database_name" {
  type = string
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