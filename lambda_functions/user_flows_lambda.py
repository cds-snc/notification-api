import json


def user_flows_handler(event, context):
    return "Hello world! events: " + json.dumps(event, indent=2)
