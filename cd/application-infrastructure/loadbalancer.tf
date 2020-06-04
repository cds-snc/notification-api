resource "aws_alb" "notification_api" {
  name            = "notification-load-balancer"
  subnets         = [data.aws_subnet.public_az_a.id, data.aws_subnet.public_az_b.id]
  security_groups = [aws_security_group.notification_api.id]
  tags            = var.default_tags
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

resource "aws_ssm_parameter" "api_host_name" {
  name        = "/dev/notification-api/api-host-name"
  description = "The notification api URL"
  type        = "String"
  value       = format("http://%s", aws_alb.notification_api.dns_name)
  tags        = var.default_tags
}

resource "aws_alb_target_group" "notification_api" {
  name        = "notification-target-group"
  port        = 6011
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.notification.id
  target_type = "ip"
  tags        = var.default_tags

  health_check {
    path    = "/_status?simple=simple"
    matcher = "200"
  }
}

resource "aws_security_group" "notification_api" {
  name        = "notification-load-balancer-security-group"
  description = "controls access to the ALB"
  vpc_id      = data.aws_vpc.notification.id
  tags        = var.default_tags

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