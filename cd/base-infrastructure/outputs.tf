output "notification_vpc_id" {
  value = aws_vpc.notification.id
}

output "notification_cluster_id" {
  value = aws_ecs_cluster.notification_fargate.id
}

output "notification_kms_key_id" {
  value = aws_kms_key.notification.id
}

output "private_subnet_ids" {
  value = aws_subnet.private.*.id
}

output "public_subnet_ids" {
  value = aws_subnet.public.*.id
}