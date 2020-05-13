module "db" {
  source                          = "terraform-aws-modules/rds-aurora/aws"

  name                            = "notification-api-db"

  engine                          = "aurora-postgresql"
  engine_version                  = "10.11"

  vpc_id                          = aws_vpc.ecs-vpc.id
  subnets                         = aws_subnet.ecs-subnet.*.id

  replica_count                   = 1
  instance_type                   = "db.m4.large"
  storage_encrypted               = true
  apply_immediately               = true
  monitoring_interval             = 10

  db_parameter_group_name         = "default"
  db_cluster_parameter_group_name = "default"
}
