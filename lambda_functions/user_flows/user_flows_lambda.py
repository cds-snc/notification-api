import json


def user_flows_handler(event, context):
    result = 1 == json.dumps(event)
    return "Result: " + result
