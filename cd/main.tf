resource "aws_vpc" "ecs-vpc" {
  cidr_block           = "10.0.0.0/24"
  enable_dns_hostnames = "true"
}

data "aws_availability_zones" "available_zones" {
}

resource "aws_subnet" "ecs-subnet" {
  count = 2
  cidr_block = cidrsubnet(aws_vpc.ecs-vpc.cidr_block, 4, count.index)
  availability_zone = data.aws_availability_zones.available_zones.names[count.index]
  vpc_id     = aws_vpc.ecs-vpc.id
}

resource "aws_subnet" "notification_subnet_public" {
  count                   = 2
  cidr_block              = cidrsubnet(aws_vpc.ecs-vpc.cidr_block, 4, 2 + count.index)
  availability_zone       = data.aws_availability_zones.available_zones.names[count.index]
  vpc_id                  = aws_vpc.ecs-vpc.id
  map_public_ip_on_launch = true
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
  subnet_ids = aws_subnet.ecs-subnet.*.id
}

resource "aws_vpc_endpoint" "vpc_endpoint_ecr_dkr" {
  vpc_id              = aws_vpc.ecs-vpc.id
  service_name        = "com.amazonaws.us-east-2.ecr.dkr"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids = aws_subnet.ecs-subnet.*.id
}

resource "aws_vpc_endpoint" "vpc_endpoint_cloudwatch" {
  vpc_id              = aws_vpc.ecs-vpc.id
  service_name        = "com.amazonaws.us-east-2.logs"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids = aws_subnet.ecs-subnet.*.id
}

resource "aws_vpc_endpoint" "vpc_endpoint_s3" {
  vpc_id            = aws_vpc.ecs-vpc.id
  service_name      = "com.amazonaws.us-east-2.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids = aws_route_table.private.*.id
}

resource "aws_internet_gateway" "notification_internet_gateway" {
  vpc_id = aws_vpc.ecs-vpc.id
}

resource "aws_eip" "eip_notification" {
  count      = 2
  vpc        = true
  depends_on = [aws_internet_gateway.notification_internet_gateway]
}

resource "aws_nat_gateway" "notification_nat" {
  count = 2
  subnet_id      = element(aws_subnet.notification_subnet_public.*.id, count.index)
  allocation_id = element(aws_eip.eip_notification.*.id, count.index)
}