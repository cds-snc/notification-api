resource "aws_ecs_task_definition" "notification_api" {
  container_definitions    = data.template_file.notification_api_container_definition.rendered
  family                   = "notification-api-task"
  execution_role_arn       = aws_iam_role.notification_ecs_task_execution.arn
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
}

resource "aws_ecs_service" "notification_api" {
  name            = "notification-api-service"
  cluster         = aws_ecs_cluster.notification_fargate.id
  task_definition = aws_ecs_task_definition.notification_api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.ecs_task_outbound_access.id]
    subnets          = aws_subnet.private.*.id
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
    app_image      = format("437518843863.dkr.ecr.us-east-2.amazonaws.com/notification_api:%s", var.app_tag)
    app_port       = 6011
    fargate_cpu    = 512
    fargate_memory = 1024
    aws_region     = "us-east-2"
    app_name       = "notification-api"
    log_group_name = aws_cloudwatch_log_group.notification.name
    
    db_user = module.db.this_rds_cluster_master_username
    db_password = module.db.this_rds_cluster_master_password
    db_endpoint = module.db.this_rds_cluster_endpoint
    db_port = module.db.this_rds_cluster_port
  }
}