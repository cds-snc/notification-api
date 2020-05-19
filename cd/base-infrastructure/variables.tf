variable "default_tags" {
  type = map(string)
  default = {
    Stack = "base-infrastructure",
    Environment = "dev",
    Team = "va-notify"
    Managed = "Terraform"
  }
}