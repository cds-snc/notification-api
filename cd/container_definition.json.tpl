[
  {
    "name": "${app_name}",
    "image": "${app_image}",
    "cpu": ${fargate_cpu},
    "memory": ${fargate_memory},
    "networkMode": "awsvpc",
    "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "${log_group_name}",
          "awslogs-region": "${aws_region}",
          "awslogs-stream-prefix": "ecs"
        }
    },
    "portMappings": [
      {
        "containerPort": ${app_port},
        "hostPort": ${app_port}
      }
    ],
    "environment": [{
        "TWILIO_ACCOUNT_SID": "account_sid",
        "TWILIO_AUTH_TOKEN": "auth_token",
        "TWILIO_FROM_NUMBER": "0123456789",
        "NOTIFY_ENVIRONMENT": "development",
        "FLASK_APP": "application.py"
    }]
  }
]