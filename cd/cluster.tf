resource "aws_ecs_cluster" "fargate" {
  name               = "notify-fargate-cluster"
  capacity_providers = ["FARGATE"]
}