resource "aws_ecs_task_definition" "ecs_task_definition" {
  container_definitions    = data.template_file.notify_api.rendered
  family                   = "notification-api-task"
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
}

resource "aws_ecs_service" "notify_api" {
  name            = "cb-service"
  cluster         = aws_ecs_cluster.fargate.id
  task_definition = aws_ecs_task_definition.ecs_task_definition.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets          = aws_subnet.private.*.id
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_alb_target_group.notify_api.id
    container_name   = "notification-api"
    container_port   = 6011
  }

  depends_on = [aws_alb_listener.notify_api, aws_iam_role_policy_attachment.ecs_task_execution_role]
}

data "template_file" "notify_api" {
  template = file("./container_definition.json.tpl")

  vars = {
    app_image      = format("437518843863.dkr.ecr.us-east-2.amazonaws.com/notification_api:%s", var.app_tag)
    app_port       = 6011
    fargate_cpu    = 512
    fargate_memory = 1024
    aws_region     = "us-east-2"
    app_name       = "notification-api"
    log_group_name = aws_cloudwatch_log_group.notify_logs.name
  }
}