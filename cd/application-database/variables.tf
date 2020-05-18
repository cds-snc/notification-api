variable "database_name" {
  type = string
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