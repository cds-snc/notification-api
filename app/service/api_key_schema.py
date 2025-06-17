update_api_key_expiry_request = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'description': 'POST service api key expiry date update',
    'type': 'object',
    'title': 'Update API key expiry date',
    'properties': {
        'expiry_date': {
            'type': 'string',
            'format': 'date',
        }
    },
    'required': ['expiry_date'],
}
