import json
import test_retrieve_everything


def user_flows_handler(event, context):
    results = test_retrieve_everything.test_retrieval(json.dumps(event))

    return results
