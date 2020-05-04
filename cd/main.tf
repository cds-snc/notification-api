provider "aws" {
  profile    = "va"
  region     = "us-east-2"
}

resource "aws_s3_bucket" "test_bucket" {
  bucket = "my-test-bucket"
  acl    = "private"
}