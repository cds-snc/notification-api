resource "aws_ecs_task_definition" "notification_api" {
  container_definitions = <<DEFINITION
[
    {
      "name": "notification-api",
      "image": "nginx:1.17.10"
    }
]
DEFINITION

  family                   = "notification-api-task"
  execution_role_arn       = aws_iam_role.notification_ecs_task_execution.arn
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  tags                     = var.default_tags
}

resource "aws_ecs_service" "notification_api" {
  name            = "notification-api-service"
  cluster         = data.aws_ecs_cluster.notification_fargate.id
  task_definition = aws_ecs_task_definition.notification_api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.ecs_task_outbound_access.id, data.terraform_remote_state.application_db.outputs.notification_db_access_security_group_id]
    subnets          = [data.aws_subnet.private_az_a.id, data.aws_subnet.private_az_b.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_alb_target_group.notification_api.id
    container_name   = "notification-api"
    container_port   = 6011
  }

  depends_on = [aws_alb_listener.notification_api, aws_iam_role_policy_attachment.notification_ecs_task_execution]

  //  Changes to the task definition will be managed by CI, not Terraform
  lifecycle {
    ignore_changes = [task_definition]
  }
}