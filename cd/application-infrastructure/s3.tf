resource "aws_s3_bucket" "assets" {
  bucket = var.environment_prefix == "prod" ? "notifications-va-gov-assets" : "${var.environment_prefix}-notifications-va-gov-assets"

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }

  tags = local.default_tags
}

resource "aws_s3_bucket_object" "va_logo" {
  bucket = aws_s3_bucket.assets.id
  key    = "va-logo.png"
  source = "assets/header-logo.png"
  etag   = filemd5("assets/header-logo.png")
  acl    = "public-read"

  tags = local.default_tags
}