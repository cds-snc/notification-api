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
  vpc_id     = aws_vpc.ecs-vpc.id
  cidr_block = "10.0.0.0/24"
}

resource "aws_ecs_cluster" "ecs-cluster" {
  name = "notify-fargate-cluster"
  capacity_providers = ["FARGATE"]
}

resource "aws_ecs_task_definition" "ecs-task-definition" {
  container_definitions = data.template_file.notification-api.rendered
  family = "notification-api-task"
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
}

resource "aws_ecs_service" "notification_api_service" {
  name            = "cb-service"
  cluster         = aws_ecs_cluster.ecs-cluster.id
  task_definition = aws_ecs_task_definition.ecs-task-definition.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets          = aws_subnet.ecs-subnet.*.id
    assign_public_ip = true
  }

  depends_on = [aws_iam_role_policy_attachment.ecs_task_execution_role]
}

resource "aws_security_group" "ecs_tasks" {
  name        = "cb-ecs-tasks-security-group"
  description = "allow outbound access"
  vpc_id      = aws_vpc.ecs-vpc.id

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "template_file" "notification-api" {
  template = file("./container_definition.json.tpl")

  vars = {
    app_image      = "437518843863.dkr.ecr.us-east-2.amazonaws.com/notification_api:latest"
    app_port       = 6011
    fargate_cpu    = 512
    fargate_memory = 1024
    aws_region     = "us-east-2"
    app_name       = "notification-api"
    log_group_name = aws_cloudwatch_log_group.notification-log-group.name
  }
}

resource "aws_cloudwatch_log_group" "notification-log-group" {
  name = "notification-log-group"
}