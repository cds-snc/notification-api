provider "aws" {
  region     = "us-east-2"
}

terraform {
  backend "s3" {
    bucket = "mybucket"
    key    = "path/to/my/key"
    region = "us-east-2"
  }
}

resource "aws_s3_bucket" "test_bucket" {
  bucket = "my-test-bucket"
  acl    = "private"
}