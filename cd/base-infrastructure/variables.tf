variable "default_tags" {
  type = map(string)
  default = {
    Stack = "base-infrastructure",
    Environment = "dev",
    Team = "va-notify"
    ManagedBy = "Terraform"
  }
}

variable "workspace_iam_roles" {
  default = {
    default = "arn:aws:iam::437518843863:role/notification-deploy-role"
  }
}