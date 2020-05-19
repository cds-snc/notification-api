resource "aws_cloudwatch_log_group" "notification" {
  name = "notification-api-log-group"
  tags = var.default_tags
}