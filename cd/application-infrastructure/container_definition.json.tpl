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
        {"name": "NOTIFY_ENVIRONMENT", "value": "${notify_environment}"},
        {"name": "FLASK_APP", "value": "application.py"}
    ],
    "secrets": [
        {"name": "TWILIO_ACCOUNT_SID", "value": "${twilio_account_sid_arn}"},
        {"name": "TWILIO_AUTH_TOKEN", "value": "${twilio_auth_token_arn}"},
        {"name": "TWILIO_FROM_NUMBER", "value": "${twilio_from_number_arn}"},
        {"name": "SQLALCHEMY_DATABASE_URI", "value": "${database_uri_arn}"}
    ]
  }
]