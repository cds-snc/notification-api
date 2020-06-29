environment_prefix = "staging"

deploy_role = "arn:aws:iam::437518843863:role/notification-deploy-role"

admin_principal = "arn:aws:iam::437518843863:role/federated-admin"

private_cidrs = ["10.0.0.0/26", "10.0.0.64/26"]

public_cidrs = ["10.0.0.128/26", "10.0.0.192/26"]

vpc_cidr = "10.0.0.0/24"

region = "us-east-2"