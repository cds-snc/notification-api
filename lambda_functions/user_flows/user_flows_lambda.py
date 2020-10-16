import test_retrieve_everything


def user_flows_handler(event, context):
    environment = event['environment']
    results = test_retrieve_everything.test_retrieval(environment)

    return {
        'results': "Tests were run for {environment}.\n RESULTS: {content}\n".format(
            environment=environment,
            content=results
        )
    }
