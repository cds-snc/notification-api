resource "random_password" "admin_client_secret" {
  length = 16
}

resource "aws_ssm_parameter" "admin_client_secret" {
  name        = "/${var.environment_prefix}/notification-api/admin-client-secret"
  description = "The notification api URL"
  type        = "SecureString"
  value       = random_password.admin_client_secret.result
  key_id      = "alias/${var.environment_prefix}-notification"
  tags        = local.default_tags
}

resource "random_password" "secret_key" {
  length = 16
}

resource "aws_ssm_parameter" "secret_key" {
  name        = "/${var.environment_prefix}/notification-api/secret-key"
  description = "The notification api URL"
  type        = "SecureString"
  value       = random_password.secret_key.result
  key_id      = "alias/${var.environment_prefix}-notification"
  tags        = local.default_tags
}

resource "random_password" "dangerous_salt" {
  length = 16
}

resource "aws_ssm_parameter" "dangerous_salt" {
  name        = "/${var.environment_prefix}/notification-api/dangerous-salt"
  description = "The notification api URL"
  type        = "SecureString"
  value       = random_password.dangerous_salt.result
  key_id      = "alias/${var.environment_prefix}-notification"
  tags        = local.default_tags
}
