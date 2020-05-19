resource "aws_ecs_task_definition" "notification_api" {
  container_definitions    = data.template_file.notification_api_container_definition.rendered
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
  tags            = var.default_tags

  network_configuration {
    security_groups  = [aws_security_group.ecs_task_outbound_access.id]
    subnets          = [data.aws_subnet.private_az_a.id, data.aws_subnet.private_az_b.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_alb_target_group.notification_api.id
    container_name   = "notification-api"
    container_port   = 6011
  }

  depends_on = [aws_alb_listener.notification_api, aws_iam_role_policy_attachment.notification_ecs_task_execution]
}

data "template_file" "notification_api_container_definition" {
  template = file("./container_definition.json.tpl")

  vars = {
    app_image          = format("437518843863.dkr.ecr.us-east-2.amazonaws.com/notification_api:%s", var.app_tag)
    app_port           = 6011
    fargate_cpu        = 512
    fargate_memory     = 1024
    aws_region         = "us-east-2"
    app_name           = "notification-api"
    log_group_name     = aws_cloudwatch_log_group.notification.name
    database_uri       = data.aws_ssm_parameter.database_uri.value
    twilio_from_number = data.aws_ssm_parameter.twilio_from_number.value
    twilio_account_sid = data.aws_ssm_parameter.twilio_account_sid.value
    twilio_auth_token  = data.aws_ssm_parameter.twilio_auth_token.value
    notify_environment = var.notify_environment
  }
}