provider "aws" {
  region = "us-east-2"
}

terraform {
  backend "s3" {
    bucket = "terraform-notification-test"
    key    = "notification-test.tfstate"
    region = "us-east-2"
  }
}

resource "aws_vpc" "ecs-vpc" {
  cidr_block           = "10.0.0.0/24"
  enable_dns_hostnames = "true"
}

resource "aws_subnet" "ecs-subnet" {
  vpc_id     = aws_vpc.ecs-vpc.id
  cidr_block = "10.0.0.0/24"
}

data "aws_availability_zones" "available_zones" {
}

resource "aws_subnet" "notification_subnet_public" {
  count                   = 2
  cidr_block              = cidrsubnet(aws_vpc.ecs-vpc.cidr_block, 8, 2 + count.index)
  availability_zone       = data.aws_availability_zones.available_zones.names[count.index]
  vpc_id                  = aws_vpc.ecs-vpc.id
  map_public_ip_on_launch = true
}

resource "aws_ecs_cluster" "ecs-cluster" {
  name               = "notify-fargate-cluster"
  capacity_providers = ["FARGATE"]
}

resource "aws_ecs_task_definition" "ecs-task-definition" {
  container_definitions    = data.template_file.notification-api.rendered
  family                   = "notification-api-task"
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
    assign_public_ip = false
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

  ingress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "vpc-private-subnet-endpoints"
  description = "Allow hosts in private subnet to talk to AWS enpoints"
  vpc_id      = aws_vpc.ecs-vpc.id

  ingress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_endpoint" "vpc_endpoint_ecr_api" {
  vpc_id              = aws_vpc.ecs-vpc.id
  service_name        = "com.amazonaws.us-east-2.ecr.api"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids = [aws_subnet.ecs-subnet.id]
}

resource "aws_vpc_endpoint" "vpc_endpoint_ecr_dkr" {
  vpc_id              = aws_vpc.ecs-vpc.id
  service_name        = "com.amazonaws.us-east-2.ecr.dkr"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids = [aws_subnet.ecs-subnet.id]
}

resource "aws_vpc_endpoint" "vpc_endpoint_cloudwatch" {
  vpc_id              = aws_vpc.ecs-vpc.id
  service_name        = "com.amazonaws.us-east-2.logs"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids = [aws_subnet.ecs-subnet.id]
}

resource "aws_vpc_endpoint" "vpc_endpoint_s3" {
  vpc_id            = aws_vpc.ecs-vpc.id
  service_name      = "com.amazonaws.us-east-2.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids = [aws_vpc.ecs-vpc.main_route_table_id]
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

resource "aws_route_table_association" "vpc_route_table_association" {
  subnet_id      = aws_subnet.ecs-subnet.id
  route_table_id = aws_vpc.ecs-vpc.main_route_table_id
}

resource "aws_internet_gateway" "notification_internet_gateway" {
  vpc_id = aws_vpc.ecs-vpc.id
}

resource "aws_eip" "eip_notification" {
  vpc        = true
  depends_on = [aws_internet_gateway.notification_internet_gateway]
}

resource "aws_nat_gateway" "notification_nat" {
  allocation_id = aws_eip.eip_notification.id
  subnet_id = aws_subnet.ecs-subnet.id
}

resource "aws_alb" "notification_alb" {
  name            = "notification-load-balancer"
  subnets         = aws_subnet.notification_subnet_public.*.id
  security_groups = [aws_security_group.notification_alb_security_group.id]
}

resource "aws_security_group" "notification_alb_security_group" {
  name        = "notification-load-balancer-security-group"
  description = "controls access to the ALB"
  vpc_id      = aws_vpc.ecs-vpc.id

  ingress {
    protocol    = "tcp"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}
