bucket             = "va-notification-terraform-staging"
environment_prefix = "staging"

# keys below are currently the same as the default values to be changed later
database_name          = "notification_api"
database_instance_type = "db.t3.medium"
region                 = "us-east-2"
workspace_iam_role     = "arn:aws:iam::437518843863:role/notification-deploy-role"
