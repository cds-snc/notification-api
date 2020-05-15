module "db" {
  source                          = "terraform-aws-modules/rds-aurora/aws"

  name                            = "notification-api-db"

  engine                          = "aurora-postgresql"
  engine_version                  = "11.6"

  vpc_id                          = aws_vpc.notification.id
  subnets                         = aws_subnet.private.*.id

  replica_count                   = 1
  instance_type                   = "db.r4.large"
  storage_encrypted               = true
  apply_immediately               = true
  monitoring_interval             = 10
}

resource "aws_security_group" "notification_db_access" {
  name_prefix = "notification-db-access-"
  description = "For access to the Notification Database"
  vpc_id      = aws_vpc.notification.id
}

resource "aws_security_group_rule" "allow_db_ingress" {
  type                     = "ingress"
  from_port                = module.db.this_rds_cluster_port
  to_port                  = module.db.this_rds_cluster_port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.notification_db_access.id
  security_group_id        = module.db.this_security_group_id
}
