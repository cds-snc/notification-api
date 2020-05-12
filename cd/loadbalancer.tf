resource "aws_alb_target_group" "notify_app" {
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

resource "aws_alb_listener" "front_end" {
  load_balancer_arn = aws_alb.notification_alb.id
  port              = 80
  protocol          = "HTTP"

  default_action {
    target_group_arn = aws_alb_target_group.notify_app.id
    type             = "forward"
  }
}

resource "aws_alb" "notification_alb" {
  name            = "notification-load-balancer"
  subnets         = aws_subnet.notification_subnet_public.*.id
  security_groups = [aws_security_group.notification_alb_security_group.id]
}