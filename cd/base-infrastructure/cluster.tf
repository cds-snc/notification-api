resource "aws_ecs_cluster" "notification_fargate" {
  name               = var.cluster_name[terraform.workspace]
  capacity_providers = ["FARGATE"]

  tags = var.default_tags
}