variable "user_flows_lambda_filename" {
  default = "user_flows_lambda.zip"
}

data "aws_iam_policy_document" "lambda_task_assume_role" {
  version = "2012-10-17"
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

variable "permissions_boundary" {
  description = "The ARN of the policy that is used to set the permissions boundary for IAM roles"
  type        = string
  default     = "arn:aws-us-gov:iam::171875617347:policy/vaec/project-admin"
}

resource "aws_iam_role" "lambda_task_execution" {
  name                 = "project-user-flows-lambda-task-execution-role"
  path                 = "/project/"
  description          = "Allows Lambda Function to call AWS services on app's behalf."
  permissions_boundary = var.permissions_boundary

  assume_role_policy = data.aws_iam_policy_document.lambda_task_assume_role.json
}

# need policy document aws_iam_policy_document.ssm_parameter_access -- api key and notification url
resource "aws_lambda_function" "user_flows_lambda" {
  role             = aws_iam_role.lambda_task_execution.arn
  handler          = "lambda_functions.user_flows_handler"
  runtime          = "python3.6"
  filename         = var.user_flows_lambda_filename
  function_name    = "user_flows_lambda"
  source_code_hash = base64sha256(var.user_flows_lambda_filename)
}