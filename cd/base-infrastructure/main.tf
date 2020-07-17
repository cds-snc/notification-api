resource "aws_vpc" "notification" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = "true"

  tags = local.default_tags
}

resource "aws_subnet" "private" {
  count             = length(var.private_cidrs)
  cidr_block        = var.private_cidrs[count.index]
  availability_zone = data.aws_availability_zones.available_zones.names[count.index]
  vpc_id            = aws_vpc.notification.id

  tags = local.default_tags
}

resource "aws_ssm_parameter" "private_subnets" {
  name        = "/${var.environment_prefix}/notification-api/subnets/private"
  description = "The IDs of the private subnets"
  type        = "String"
  value       = join(",", aws_subnet.private.*.id)
  tags        = local.default_tags
}

resource "aws_subnet" "public" {
  count                   = length(var.public_cidrs)
  cidr_block              = var.public_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.available_zones.names[count.index]
  vpc_id                  = aws_vpc.notification.id
  map_public_ip_on_launch = true

  tags = local.default_tags
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.environment_prefix}-notification-private-subnet-endpoints"
  description = "Allow hosts in private subnet to talk to AWS enpoints"
  vpc_id      = aws_vpc.notification.id

  ingress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.default_tags
}

resource "aws_ssm_parameter" "vpc_endpoints_security_group" {
  name        = "/${var.environment_prefix}/notification-api/security-group/access-endpoints"
  description = "The ID of the security group that allows VPC endpoint access"
  type        = "String"
  value       = aws_security_group.vpc_endpoints.id
  tags        = local.default_tags
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.notification.id
  service_name        = "com.amazonaws.${var.region}.ecr.api"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private.*.id

  tags = local.default_tags
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.notification.id
  service_name        = "com.amazonaws.${var.region}.ecr.dkr"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private.*.id

  tags = local.default_tags
}

resource "aws_vpc_endpoint" "cloudwatch" {
  vpc_id              = aws_vpc.notification.id
  service_name        = "com.amazonaws.${var.region}.logs"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private.*.id

  tags = local.default_tags
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.notification.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private.*.id

  tags = local.default_tags
}

resource "aws_vpc_endpoint" "sqs" {
  vpc_id              = aws_vpc.notification.id
  service_name        = "com.amazonaws.${var.region}.sqs"
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private.*.id

  tags = local.default_tags
}

resource "aws_internet_gateway" "notification" {
  vpc_id = aws_vpc.notification.id

  tags = local.default_tags
}

resource "aws_eip" "notification" {
  count      = length(var.public_cidrs)
  vpc        = true
  depends_on = [aws_internet_gateway.notification]

  tags = local.default_tags
}

resource "aws_nat_gateway" "notification" {
  count         = length(var.public_cidrs)
  subnet_id     = element(aws_subnet.public.*.id, count.index)
  allocation_id = element(aws_eip.notification.*.id, count.index)

  tags = local.default_tags
}