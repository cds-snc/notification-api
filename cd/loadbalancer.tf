resource "aws_alb" "notify_alb" {
  name            = "notification-load-balancer"
  subnets         = aws_subnet.notification_subnet_public.*.id
  security_groups = [aws_security_group.notify_alb.id]
}

resource "aws_alb_listener" "notify_api" {
  load_balancer_arn = aws_alb.notify_alb.id
  port              = 80
  protocol          = "HTTP"

  default_action {
    target_group_arn = aws_alb_target_group.notify_api.id
    type             = "forward"
  }
}

resource "aws_alb_target_group" "notify_api" {
  name        = "notification-target-group"
  port        = 6011
  protocol    = "HTTP"
  vpc_id      = aws_vpc.ecs-vpc.id
  target_type = "ip"

  health_check {
    path = "/_status?simple=simple"
    matcher = "200"
  }
}

resource "aws_security_group" "notify_alb" {
  name        = "notification-load-balancer-security-group"
  description = "controls access to the ALB"
  vpc_id      = aws_vpc.ecs-vpc.id

  ingress {
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}