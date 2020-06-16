resource "random_password" "admin_client_secret" {
  length = 16
}

resource "aws_ssm_parameter" "admin_client_secret" {
  name        = "/dev/notification-api/admin-client-secret"
  description = "The notification api URL"
  type        = "SecureString"
  value       = random_password.admin_client_secret.result
  tags        = local.default_tags
}

resource "random_password" "secret_key" {
  length = 16
}

resource "aws_ssm_parameter" "secret_key" {
  name        = "/dev/notification-api/secret-key"
  description = "The notification api URL"
  type        = "SecureString"
  value       = random_password.secret_key.result
  tags        = local.default_tags
}

resource "random_password" "dangerous_salt" {
  length = 16
}

resource "aws_ssm_parameter" "dangerous_salt" {
  name        = "/dev/notification-api/dangerous-salt"
  description = "The notification api URL"
  type        = "SecureString"
  value       = random_password.dangerous_salt.result
  tags        = local.default_tags
}
