resource "aws_route_table" "notification_route_table" {
  vpc_id = aws_vpc.ecs-vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.notification_internet_gateway.id
  }
}

resource "aws_route_table_association" "vpc_route_table_association" {
  count = 2
  subnet_id      = element(aws_subnet.ecs-subnet.*.id, count.index)
  route_table_id = aws_route_table.notification_route_table.id
}