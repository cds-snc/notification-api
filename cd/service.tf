resource "aws_ecs_task_definition" "ecs-task-definition" {
  container_definitions    = data.template_file.notification-api.rendered
  family                   = "notification-api-task"
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
}

resource "aws_ecs_service" "notification_api_service" {
  name            = "cb-service"
  cluster         = aws_ecs_cluster.ecs-cluster.id
  task_definition = aws_ecs_task_definition.ecs-task-definition.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets          = aws_subnet.ecs-subnet.*.id
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_alb_target_group.notify_app.id
    container_name   = "notification-api"
    container_port   = 6011
  }

  depends_on = [aws_alb_listener.front_end, aws_iam_role_policy_attachment.ecs_task_execution_role]
}

data "template_file" "notification-api" {
  template = file("./container_definition.json.tpl")

  vars = {
    app_image      = "437518843863.dkr.ecr.us-east-2.amazonaws.com/notification_api:latest"
    app_port       = 6011
    fargate_cpu    = 512
    fargate_memory = 1024
    aws_region     = "us-east-2"
    app_name       = "notification-api"
    log_group_name = aws_cloudwatch_log_group.notification-log-group.name
  }
}