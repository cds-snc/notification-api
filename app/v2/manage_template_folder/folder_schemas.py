from app.schema_validation.definitions import nullable_uuid, uuid

get_template_folder_by_id_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "GET/PATCH/DELETE schema for a single manage template folder",
    "type": "object",
    "properties": {"id": uuid},
    "required": ["id"],
}

post_manage_template_folder_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST schema for creating a manage template folder",
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "parent_folder_id": nullable_uuid,
    },
    "required": ["name"],
    "additionalProperties": False,
}

patch_manage_template_folder_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "PATCH schema for renaming or moving a manage template folder",
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "parent_folder_id": nullable_uuid,
    },
    "additionalProperties": False,
}
