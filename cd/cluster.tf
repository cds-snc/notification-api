resource "aws_ecs_cluster" "ecs-cluster" {
  name               = "notify-fargate-cluster"
  capacity_providers = ["FARGATE"]
}