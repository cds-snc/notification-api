resource "aws_route_table" "public" {
  vpc_id = aws_vpc.ecs-vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.notification_internet_gateway.id
  }
}

resource "aws_route_table_association" "public" {
  count = 2
  subnet_id      = element(aws_subnet.notification_subnet_public.*.id, count.index)
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count = 2
  vpc_id = aws_vpc.ecs-vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = element(aws_nat_gateway.notification_nat.*.id, count.index)
  }
}

resource "aws_route_table_association" "private" {
  count = 2
  subnet_id      = element(aws_subnet.ecs-subnet.*.id, count.index)
  route_table_id = elemeent(aws_route_table.private.*.id, count.index)
}