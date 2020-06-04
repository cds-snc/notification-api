resource "aws_cloudwatch_log_group" "notification" {
  name = "notification-api-log-group"
  retention_in_days = 7
  tags = var.default_tags
}