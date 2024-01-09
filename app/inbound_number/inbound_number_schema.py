# Creation schema
post_create_inbound_number_schema = {
    '$schema': 'http://json-schema.org/draft/2020-12/schema#',
    'description': 'POST create inbound number schema',
    'type': 'object',
    'properties': {
        'active': {'type': 'boolean'},
        'number': {'type': 'string'},
        'provider': {'type': 'string'},
        'self_managed': {'type': 'boolean'},
        'service_id': {'type': 'string'},
        'url_endpoint': {'type': 'string'},
        'auth_parameter': {'type': 'string'},
    },
    'required': ['number', 'provider'],
    'if': {
        'properties': {
            'self_managed': {'const': True},
        },
        'required': ['self_managed'],
    },
    'then': {
        'required': ['url_endpoint'],
    },
    'additionalProperties': False,
}


# Update schema.  This is the creation schema without some of the required attributes.
post_update_inbound_number_schema = post_create_inbound_number_schema.copy()
post_update_inbound_number_schema['description'] = 'POST update inbound number schema'
del post_update_inbound_number_schema['required']
