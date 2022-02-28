# Docker image for the heartbeat hitting the lambda API.

FROM public.ecr.aws/lambda/python:3.9

ENV PYTHONDONTWRITEBYTECODE 1

# Install the function's dependencies
COPY heartbeat/requirements_for_heartbeat.txt ${LAMBDA_TASK_ROOT}
RUN python -m pip install -r requirements_for_heartbeat.txt

# Copy function code
COPY heartbeat/heartbeat.py ${LAMBDA_TASK_ROOT}

CMD [ "heartbeat.handler" ]
