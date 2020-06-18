module "db" {
  source = "terraform-aws-modules/rds-aurora/aws"

  name = "${var.environment_prefix}-notification-api-db"

  engine         = "aurora-postgresql"
  engine_version = "11.6"

  vpc_id  = data.terraform_remote_state.base_infrastructure.outputs.notification_vpc_id
  subnets = [data.aws_subnet.private_az_a.id, data.aws_subnet.private_az_b.id]

  replica_count       = 1
  instance_type       = var.database_instance_type
  storage_encrypted   = true
  apply_immediately   = true
  monitoring_interval = 10

  database_name = var.database_name
  tags          = local.default_tags
}

resource "aws_ssm_parameter" "database_uri" {
  name        = "/${var.environment_prefix}/notification-api/database/uri"
  description = "The database URI for ${var.environment_prefix}"
  type        = "SecureString"
  value       = format(
                  "postgresql://%s:%s@%s:%s/%s",
                  module.db.this_rds_cluster_master_username,
                  module.db.this_rds_cluster_master_password,
                  module.db.this_rds_cluster_endpoint,
                  module.db.this_rds_cluster_port,
                  module.db.this_rds_cluster_database_name)
  tags        = local.default_tags
}

resource "aws_security_group" "notification_db_access" {
  name_prefix = "${var.environment_prefix}-notification-db-access-"
  description = "For access to the Notification Database"
  vpc_id      = data.terraform_remote_state.base_infrastructure.outputs.notification_vpc_id

  revoke_rules_on_delete = true
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_ssm_parameter" "database_access_security_group" {
  name        = "/${var.environment_prefix}/notification-api/security-group/access-db"
  description = "The ID of the security group that allows DB access"
  type        = "String"
  value       = aws_security_group.notification_db_access.id
  tags        = local.default_tags
}

resource "aws_security_group_rule" "allow_db_ingress" {
  type                     = "ingress"
  from_port                = module.db.this_rds_cluster_port
  to_port                  = module.db.this_rds_cluster_port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.notification_db_access.id
  security_group_id        = module.db.this_security_group_id
}
