communication_item_base_schema = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'default_send_indicator': {'type': 'boolean'},
        'name': {'type': 'string', 'minLength': 1},
        'va_profile_item_id': {'type': 'integer', 'minimum': 1},
    },
    'additionalProperties': False,
}


communication_item_post_schema = communication_item_base_schema.copy()
communication_item_post_schema['required'] = ['name', 'va_profile_item_id']


communication_item_patch_schema = communication_item_base_schema.copy()
communication_item_patch_schema['minProperties'] = 1
