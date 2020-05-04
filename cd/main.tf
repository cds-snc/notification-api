provider "aws" {
  region     = "us-east-2"
}

terraform {
  backend "s3" {
    bucket = "terraform-notification-test"
    key    = "notification-test.tfstate"
    region = "us-east-2"
  }
}
resource "aws_vpc" "ecs-vpc" {
  cidr_block = "10.0.0.0/24"
}
resource "aws_subnet" "ecs-subnet" {
  vpc_id     = "aws_vpc.ecs-vpc.id"
  cidr_block = "10.0.0.0/28"
}
resource "aws_ecs_cluster" "ecs-cluster" {
  name = "notify-fargate-cluster"
  capacity_providers = ["FARGATE"]
}