ga4_request_schema = {
    '$schema': 'http://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'properties': {
        # The campaign maxLength matches the definition in models.py of TemplateBase.name.
        'campaign': {'type': 'string', 'minLength': 1, 'maxLength': 255},
        'campaign_id': {'type': 'string', 'format': 'uuid'},
        'name': {'const': 'email_open'},
        'source': {'const': 'vanotify'},
        'medium': {'const': 'email'},
        'content': {
            'type': 'string',
            # {notification.service.name}/{notification.service.id}/{notification.id}
            # https://json-schema.org/understanding-json-schema/reference/regular_expressions
            'pattern': '^[^/]{1,255}/[0-9a-zA-Z-]{36}/[0-9a-zA-Z-]{36}$',
        },
    },
    'additionalProperties': False,
    'required': ['campaign', 'campaign_id', 'name', 'source', 'medium', 'content'],
}
