resource "aws_route_table" "public" {
  vpc_id = aws_vpc.notify.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.notify_internet_gateway.id
  }
}

resource "aws_route_table_association" "public" {
  count = 2
  subnet_id      = element(aws_subnet.public.*.id, count.index)
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count = 2
  vpc_id = aws_vpc.notify.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = element(aws_nat_gateway.notify_nat.*.id, count.index)
  }
}

resource "aws_route_table_association" "private" {
  count = 2
  subnet_id      = element(aws_subnet.private.*.id, count.index)
  route_table_id = element(aws_route_table.private.*.id, count.index)
}