provider "aws" {
  region = "us-east-2"

  assume_role {
    role_arn     = "arn:aws:iam::437518843863:role/notification-deploy-role"
  }
}

provider "postgresql" {
  host            = module.db.this_rds_cluster_endpoint
  port            = module.db.this_rds_cluster_port
  database        = module.db.this_rds_cluster_database_name
  username        = module.db.this_rds_cluster_master_username
  password        = module.db.this_rds_cluster_master_password
  sslmode         = "require"
  connect_timeout = 15
}

terraform {
  backend "s3" {
    bucket = "terraform-notification-test"
    key    = "notification-test.tfstate"
    region = "us-east-2"
    encrypt = true
  }
}