resource "aws_security_group" "ecs_task_outbound_access" {
  name        = "ecs-task-outbound-access-security-group"
  description = "allow outbound access"
  vpc_id      = data.terraform_remote_state.base_infrastructure.outputs.notification_vpc_id
  tags        = local.default_tags

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ssm_parameter" "outbound_access_security_group" {
  name        = "/${var.environment_prefix}/notification-api/security-group/access-outbound"
  description = "The ID of the security group that allows outbound access"
  type        = "String"
  value       = aws_security_group.ecs_task_outbound_access.id
  tags        = local.default_tags
}

resource "aws_security_group" "notification_db_access" {
  name_prefix = "notification-db-access-"
  description = "For access to the Notification Database"
  vpc_id      = data.terraform_remote_state.base_infrastructure.outputs.notification_vpc_id
}