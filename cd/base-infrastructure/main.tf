resource "aws_vpc" "notification" {
  cidr_block           = "10.0.0.0/24"
  enable_dns_hostnames = "true"

  tags = var.default_tags
}

data "aws_availability_zones" "available_zones" {
}

resource "aws_subnet" "private" {
  count = 2
  cidr_block = cidrsubnet(aws_vpc.notification.cidr_block, 2, count.index)
  availability_zone = data.aws_availability_zones.available_zones.names[count.index]
  vpc_id     = aws_vpc.notification.id

  tags = var.default_tags
}

resource "aws_subnet" "public" {
  count                   = 2
  cidr_block              = cidrsubnet(aws_vpc.notification.cidr_block, 2, 2 + count.index)
  availability_zone       = data.aws_availability_zones.available_zones.names[count.index]
  vpc_id                  = aws_vpc.notification.id
  map_public_ip_on_launch = true

  tags = var.default_tags
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "vpc-private-subnet-endpoints"
  description = "Allow hosts in private subnet to talk to AWS enpoints"
  vpc_id      = aws_vpc.notification.id

  ingress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.default_tags
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.notification.id
  service_name        = "com.amazonaws.us-east-2.ecr.api"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids = aws_subnet.private.*.id

  tags = var.default_tags
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.notification.id
  service_name        = "com.amazonaws.us-east-2.ecr.dkr"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids = aws_subnet.private.*.id

  tags = var.default_tags
}

resource "aws_vpc_endpoint" "cloudwatch" {
  vpc_id              = aws_vpc.notification.id
  service_name        = "com.amazonaws.us-east-2.logs"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids = aws_subnet.private.*.id

  tags = var.default_tags
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.notification.id
  service_name      = "com.amazonaws.us-east-2.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids = aws_route_table.private.*.id

  tags = var.default_tags
}

resource "aws_internet_gateway" "notification" {
  vpc_id = aws_vpc.notification.id

  tags = var.default_tags
}

resource "aws_eip" "notification" {
  count      = 2
  vpc        = true
  depends_on = [aws_internet_gateway.notification]

  tags = var.default_tags
}

resource "aws_nat_gateway" "notification" {
  count = 2
  subnet_id      = element(aws_subnet.public.*.id, count.index)
  allocation_id = element(aws_eip.notification.*.id, count.index)

  tags = var.default_tags
}