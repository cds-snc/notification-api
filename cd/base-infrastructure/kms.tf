resource "aws_kms_key" "notification" {
  description             = "Notification KMS Key"
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.notification.json

  tags = local.default_tags
}

output "notification_kms_key_id" {
  value = aws_kms_key.notification.id
}

resource "aws_kms_alias" "notification" {
  name          = "alias/notification"
  target_key_id = aws_kms_key.notification.key_id
}

data "aws_iam_policy_document" "notification" {
  statement {
    sid = "Allow access for Key Administrators"

    effect = "Allow"

    principals {
      identifiers = [
        var.deploy_role,
        var.admin_principal
      ]
      type = "AWS"
    }

    actions = [
      "kms:Create*",
      "kms:Describe*",
      "kms:Enable*",
      "kms:List*",
      "kms:Put*",
      "kms:Update*",
      "kms:Revoke*",
      "kms:Disable*",
      "kms:Get*",
      "kms:Delete*",
      "kms:TagResource",
      "kms:UntagResource",
      "kms:ScheduleKeyDeletion",
      "kms:CancelKeyDeletion"
    ]

    resources = [
      "*",
    ]
  }

  statement {
    sid = "Allow use of the key"

    effect = "Allow"

    principals {
      identifiers = [var.deploy_role]
      type = "AWS"
    }

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey"
    ]

    resources = [
      "*"
    ]
  }

  statement {
    sid = "Allow attachment of persistent resources"

    effect = "Allow"

    principals {
      identifiers = [var.deploy_role]
      type = "AWS"
    }

    actions = [
      "kms:CreateGrant",
      "kms:ListGrants",
      "kms:RevokeGrant"
    ]

    resources = [
      "*"
    ]

    condition {
      test = "Bool"
      values = ["true"]
      variable = "kms:GrantIsForAWSResource"
    }
  }
}