locals {
  domain_name = var.environment_prefix == "prod" ? "api.twnotify.com" : "${var.environment_prefix}.api.twnotify.com"
}

data "aws_route53_zone" "notification" {
  name         = "twnotify.com."
}

resource "aws_route53_record" "notification" {
  zone_id = data.aws_route53_zone.notification.zone_id
  name    = local.domain_name
  type    = "A"

  alias {
    name                   = aws_alb.notification_api.dns_name
    zone_id                = aws_alb.notification_api.zone_id
    evaluate_target_health = true
  }
}

resource "aws_acm_certificate" "cert" {
  domain_name       = local.domain_name
  validation_method = "DNS"

  tags = local.default_tags
}

resource "aws_route53_record" "cert_validation" {
  name    = aws_acm_certificate.cert.domain_validation_options.0.resource_record_name
  type    = aws_acm_certificate.cert.domain_validation_options.0.resource_record_type
  zone_id = data.aws_route53_zone.notification.zone_id
  records = [aws_acm_certificate.cert.domain_validation_options.0.resource_record_value]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "cert" {
  certificate_arn         = aws_acm_certificate.cert.arn
  validation_record_fqdns = [aws_route53_record.cert_validation.fqdn]
}