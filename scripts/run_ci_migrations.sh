#!/bin/bash
# from https://gist.github.com/victorcoder/3ac4aae9279d7c68c486fecccc2546cc
# modified to use fargate launch type
# removed outer retry loop, because we don't expect to get CPU/memory resources errors with Fargate
# removed inner loop, because the migration should hopefully never take longer than 10 minutes (default aws ecs wait timeout)
# modified to make requests to AWS SSM, to then construct a network configuration
# modified to take DRY_RUN as an argument, not an env variable
set -e

usage() {
    set -e
    cat <<EOM
    ##### ecs-run #####
    Simple script for running tasks on Amazon Elastic Container Service
    One of the following is required:
    Required arguments:
        -t | --task-definition       Name of task definition to deploy
        -c | --cluster               Name of ECS cluster
        -e | --environment           Environment name, used as prefix for SSM parameters (e.g. "dev", "prod")

    Optional arguments:
        -v | --verbose          Verbose output
        -d | --dry-run          Dry run - don't actually execute aws ecs run-task
    Requirements:
        aws:  AWS Command Line Interface
        jq:   Command-line JSON processor
    Examples:
      Simple deployment of a service (Using env vars for AWS settings):
        ecs-run -c production1 -t foo-taskdef -e dev
      All options:
EOM

    exit 2
}
if [ $# == 0 ]; then usage; fi

# Check requirements
require() {
    command -v $1 > /dev/null 2>&1 || {
        echo "Some of the required software is not installed:"
        echo "    please install $1" >&2;
        exit 1;
    }
}

# Check for AWS, AWS Command Line Interface
require aws
# Check for jq, Command-line JSON processor
require jq

# Setup default values for variables
CLUSTER=false
TASK_DEFINITION=false
ENVIRONMENT=false
VERBOSE=false
DRY_RUN=false

# Loop through arguments, two at a time for key and value
while [[ $# > 0 ]]
do
    key="$1"

    case $key in
        -c|--cluster)
            CLUSTER="$2"
            shift # past argument
            ;;
        -t|--task-definition)
            TASK_DEFINITION="$2"
            shift
            ;;
        -e|--environment)
            ENVIRONMENT="$2"
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            ;;
        -d|--dry-run)
            DRY_RUN=true
            ;;
        *)
            echo "ERROR: $1 is not a valid option"
            usage
            exit 2
        ;;
    esac
    shift # past argument or value
done

AWS_CLI="$(which aws) --output json"

if [ $DRY_RUN == true ]; then
    AWS_ECS="echo $AWS_CLI ecs"
else
    AWS_ECS="$AWS_CLI ecs"
fi

if [ $VERBOSE == true ]; then
    set -x
fi

if [ $TASK_DEFINITION == false ]; then
    echo "TASK DEFINITON is required. You can pass the value using -t / --task-definiton for a task"
    exit 1
fi
if [ $CLUSTER == false ]; then
    echo "CLUSTER is required. You can pass the value using -c or --cluster"
    exit 1
fi
if [ $ENVIRONMENT == false ]; then
    echo "ENVIRONMENT is required. You can pass the value using -e or --environment"
    exit 1
fi

get_parameter_value() {
    local env=$1
    local name=$2

    local get_parameter_result
    get_parameter_result=$($AWS_CLI ssm get-parameter --name /$env/notification-api/$name | jq -r '.Parameter.Value')

    local returned_value=$?
    echo $get_parameter_result
    return $returned_value
}

run_task () {
    local private_subnets
    private_subnets=$(get_parameter_value dev subnets/private)

    local security_group_access_db
    security_group_access_db=$(get_parameter_value dev security-group/access-db)

    local security_group_access_outbound
    security_group_access_outbound=$(get_parameter_value dev security-group/access-outbound)

    local network_configuration="awsvpcConfiguration={subnets=[$private_subnets],securityGroups=[$security_group_access_db,$security_group_access_outbound],assignPublicIp=DISABLED}"

    local run_result
    run_result=$($AWS_ECS run-task \
                          --cluster $CLUSTER \
                          --task-definition $TASK_DEFINITION \
                          --network-configuration $network_configuration \
                          --launch-type FARGATE)
    local returned_value=$?
    echo $run_result
    return $returned_value
}


REASON_FAILURE=''
RUN_TASK=$(run_task)
RUN_TASK_EXIT_CODE=$?

echo $RUN_TASK
if [ $DRY_RUN == false ]; then
    FAILURES=$(echo $RUN_TASK | jq '.failures|length')
    if [ $FAILURES -eq 0 ]; then
        TASK_ARN=$(echo $RUN_TASK | jq '.tasks[0].taskArn' | sed -e 's/^"//' -e 's/"$//')
        $AWS_ECS wait tasks-stopped --tasks "$TASK_ARN" --cluster $CLUSTER 2>/dev/null
        WAITER_EXIT_CODE=$?

        if [ $WAITER_EXIT_CODE -eq 0 ]; then
            DESCRIBE_TASKS=$($AWS_ECS describe-tasks --tasks "$TASK_ARN" --cluster $CLUSTER)
            CONTAINER_EXIT_CODE=$(echo $DESCRIBE_TASKS | jq '.tasks[0].containers[0].exitCode')
            if [ $CONTAINER_EXIT_CODE -eq 0 ]; then
              echo "ECS task exited successfully"
              exit 0
            else
              echo "ECS task failed: $DESCRIBE_TASKS"
              exit $CONTAINER_EXIT_CODE
            fi

        elif [ $WAITER_EXIT_CODE -eq 255 ]; then
            echo "ECS Waiter because timeout"
            exit 255
        else
            echo "ECS Waiter failed, status: $WAITER_EXIT_CODE"
            exit $WAITER_EXIT_CODE
        fi
    else
        REASON_FAILURE=$(echo $RUN_TASK | jq -r '.failures[0].reason')
        echo "ECS task failed: $REASON_FAILURE"
        exit 1
    fi
fi