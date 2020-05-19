resource "aws_ecs_cluster" "notification_fargate" {
  name               = "notification-fargate-cluster"
  capacity_providers = ["FARGATE"]

  tags = var.default_tags
}