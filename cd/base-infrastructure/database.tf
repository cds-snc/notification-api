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
