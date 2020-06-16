resource "aws_ecs_cluster" "notification_fargate" {
  name               = "${var.environment_prefix}-notification-cluster"
  capacity_providers = ["FARGATE"]

  tags = local.default_tags
}
