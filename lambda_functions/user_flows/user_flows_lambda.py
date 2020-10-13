import json


def user_flows_handler(event, context):
    result = 1 == event
    return "Result is: " + result
