resource "aws_ecs_cluster" "fargate" {
  name               = "notification-fargate-cluster"
  capacity_providers = ["FARGATE"]
}