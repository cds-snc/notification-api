resource "aws_cloudwatch_log_group" "notification" {
  name              = "${var.environment_prefix}-notification-api-log-group"
  retention_in_days = var.log_retention_in_days
  tags              = local.default_tags
}

resource "aws_cloudwatch_log_group" "datadog" {
  name              = "${var.environment_prefix}-notification-api-datadog-log-group"
  retention_in_days = var.log_retention_in_days
  tags              = local.default_tags
}