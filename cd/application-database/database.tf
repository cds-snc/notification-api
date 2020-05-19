module "db" {
  source = "terraform-aws-modules/rds-aurora/aws"

  name = "notification-api-db"

  engine         = "aurora-postgresql"
  engine_version = "11.6"

  vpc_id  = data.aws_vpc.notification.id
  subnets = [data.aws_subnet.private_az_a.id, data.aws_subnet.private_az_b.id]

  replica_count       = 1
  instance_type       = "db.t3.medium"
  storage_encrypted   = true
  apply_immediately   = true
  monitoring_interval = 10

  database_name = var.database_name
  tags          = var.default_tags
}

resource "aws_ssm_parameter" "database_uri" {
  name        = "/dev/notification-api/database/uri"
  description = "The database URI for dev"
  type        = "SecureString"
  value       = format("postgresql://%s:%s@%s:%s/%s", module.db.this_rds_cluster_master_username, module.db.this_rds_cluster_master_password, module.db.this_rds_cluster_endpoint, module.db.this_rds_cluster_port, module.db.this_rds_cluster_database_name)
  tags        = var.default_tags
}