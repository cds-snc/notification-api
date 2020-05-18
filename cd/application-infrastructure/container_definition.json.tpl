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
    "environment": [
        {"name": "TWILIO_ACCOUNT_SID", "value": "account_sid"},
        {"name": "TWILIO_AUTH_TOKEN", "value": "auth_token"},
        {"name": "TWILIO_FROM_NUMBER", "value": "0123456789"},
        {"name": "NOTIFY_ENVIRONMENT", "value": "development"},
        {"name": "FLASK_APP", "value": "application.py"}
    ]
  }
]