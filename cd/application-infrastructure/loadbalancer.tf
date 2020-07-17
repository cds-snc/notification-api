resource "aws_alb" "notification_api" {
  name            = "${var.environment_prefix}-notification-alb"
  subnets         = data.terraform_remote_state.base_infrastructure.outputs.public_subnet_ids
  security_groups = [aws_security_group.notification_api.id]
  tags            = local.default_tags
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

resource "aws_alb_listener" "notification_api_https" {
  load_balancer_arn = aws_alb.notification_api.id
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = aws_acm_certificate.cert.arn
  ssl_policy        = "ELBSecurityPolicy-TLS-1-2-2017-01"

  default_action {
    target_group_arn = aws_alb_target_group.notification_api.id
    type             = "forward"
  }
}

resource "aws_ssm_parameter" "api_host_name" {
  name        = "/${var.environment_prefix}/notification-api/api-host-name"
  description = "The notification api URL"
  type        = "String"
  value       = format("http://%s", aws_alb.notification_api.dns_name)
  tags        = local.default_tags
}

resource "aws_alb_target_group" "notification_api" {
  name        = "${var.environment_prefix}-notification-group"
  port        = 6011
  protocol    = "HTTP"
  vpc_id      = data.terraform_remote_state.base_infrastructure.outputs.notification_vpc_id
  target_type = "ip"
  tags        = local.default_tags

  health_check {
    path    = "/_status?simple=simple"
    matcher = "200"
  }
}

resource "aws_security_group" "notification_api" {
  name        = "${var.environment_prefix}-notification-alb"
  description = "controls access to the ALB"
  vpc_id      = data.terraform_remote_state.base_infrastructure.outputs.notification_vpc_id
  tags        = local.default_tags

  ingress {
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}