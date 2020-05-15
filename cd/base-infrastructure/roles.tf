# ECS task execution role data
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

# ECS task execution role
resource "aws_iam_role" "notification_ecs_task_execution" {
  name               = "notification-api-ecs-task-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

# ECS task execution role policy attachment
resource "aws_iam_role_policy_attachment" "notification_ecs_task_execution" {
  role       = aws_iam_role.notification_ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}