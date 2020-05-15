resource "aws_alb" "notification_api" {
  name            = "notification-load-balancer"
  subnets         = aws_subnet.public.*.id
  security_groups = [aws_security_group.notification_api.id]
}

resource "aws_alb_listener" "notification_api" {
  load_balancer_arn = aws_alb.notification_api.id
  port              = 80
  protocol          = "HTTP"

  default_action {
    target_group_arn = aws_alb_target_group.notification_api.id
    type             = "forward"
  }
}

resource "aws_alb_target_group" "notification_api" {
  name        = "notification-target-group"
  port        = 6011
  protocol    = "HTTP"
  vpc_id      = aws_vpc.notification.id
  target_type = "ip"

  health_check {
    path = "/_status?simple=simple"
    matcher = "200"
  }
}

resource "aws_security_group" "notification_api" {
  name        = "notification-load-balancer-security-group"
  description = "controls access to the ALB"
  vpc_id      = aws_vpc.notification.id

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