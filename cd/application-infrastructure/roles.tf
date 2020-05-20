data "aws_iam_policy_document" "ecs_task_assume_role" {
  version = "2012-10-17"
  statement {
    sid     = ""
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "notification_ecs_task_execution" {
  name               = "notification-api-ecs-task-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = var.default_tags
}

resource "aws_iam_role_policy_attachment" "notification_ecs_task_execution" {
  role       = aws_iam_role.notification_ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy_attachment" "notification_ecs_task_ssm_fetch" {
  role = aws_iam_role.notification_ecs_task_execution.name
  policy_arn = aws_iam_policy.notification_ecs_task_secrets_fetch.arn
}

resource "aws_iam_policy" "notification_ecs_task_secrets_fetch" {
  name = "notification-ecs-task-secrets-fetch"
  policy = data.aws_iam_policy_document.ssm_parameter_fetch.json
}

data "aws_iam_policy_document" "ssm_parameter_fetch" {
  statement {
    sid = "FetchNotificationSecrets"

    actions = [
      "ssm:GetParametersByPath",
      "ssm:GetParameters",
      "ssm:GetParameter",
      "ssm:DescribeParameters"
    ]

    resources = [
      data.aws_ssm_parameter.database_uri.arn,
      data.aws_ssm_parameter.twilio_account_sid.arn,
      data.aws_ssm_parameter.twilio_auth_token.arn,
      data.aws_ssm_parameter.twilio_from_number.arn
    ]
  }
}